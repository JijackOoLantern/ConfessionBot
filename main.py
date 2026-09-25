import os
import sys
import datetime
import time
import re
import asyncio
import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    Application
)
from telegram.error import BadRequest, TelegramError, NetworkError
from typing import Set, Dict, Any, Union
import pytz

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TIMEZONE = pytz.timezone('Asia/Kuala_Lumpur') 
BOT_START_TIME = datetime.datetime.now()

START_HOUR = 21  
END_HOUR = 18    

LINKS_ENABLED = True
PHOTOS_ENABLED = True
AUTO_REPLY_ENABLED = True
AUTO_REPLY_TEXT = "Use @TapahConfessionBot to submit your confession\n\nIf you're trying to contact the owner, just leave the message as-is.\n\n-Dev"
AUTO_REPLY_PAUSE_DURATION = 86400

TIER_CONFIG = {
    'basic': {
        'name': 'Normal User (Default)',
        'link_cooldown': 14400,   
        'photo_cooldown': 14400,  
        'personal_queue_duration': 180,  # Updated to 3 minutes    
        'delete_cooldown': 60,  
        'delete_access': 'own',
        'price': 0,
        'duration_days': 0
    },
    'tier1': {
        'name': 'Tier 1 Premium',
        'link_cooldown': 14400,   
        'photo_cooldown': 14400,  
        'personal_queue_duration': 15,      
        'delete_cooldown': 30,    
        'delete_access': 'all',
        'price': 100,             
        'duration_days': 14       
    },
    'tier2': {
        'name': 'Tier 2 Premium',
        'link_cooldown': 14400,   
        'photo_cooldown': 21600,  
        'personal_queue_duration': 15,      
        'delete_cooldown': 60,    
        'delete_access': 'all',
        'price': 50,              
        'duration_days': 14       
    },
    'club': {
        'name': 'Club/Association Sub',
        'link_cooldown': 3600,    
        'photo_cooldown': 3600,   
        'personal_queue_duration': 15,      
        'delete_cooldown': 0,     
        'delete_access': 'own',
        'price': 200,             
        'duration_days': 30       
    }
}

PERK_CONFIG = {
    'immunity': {
        'name': 'Immunity Perk',
        'desc': 'Post cannot be deleted by others',
        'price': 100,             
        'duration_hours': 12      
    },
    'spotlight': {
        'name': 'Spotlight Perk',
        'desc': 'Instantly skips the post queue',
        'price': 100,             
        'duration_hours': 12      
    }
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
    "<b>UiTM Tapah Confession & Marketplace Bot Guide.</b>\n\n"
    "<u>Posts & Queue</u>\n"
    "- Posts are anonymous and will be queued according to subscription level to prevent spam.\n"
    "- Queue Example: Basic Level user waits 3 minutes. Next user waits 6 mins, etc.\n\n"
    "<u>Marketplace / Advertisements 🛒</u>\n"
    "- Ads are STRICTLY posted to the Marketplace channel.\n"
    "- <b>Ad Requirements:</b> An ad MUST contain at least a photo, a link, a phone number, or a Telegram username (@). Ads without these will be rejected.\n"
    "- <b>Strict Penalty:</b> Posting a regular confession inside the Ad channel, OR posting an advertisement inside the Confession channel, will result in an immediate 1-WEEK (10080 minutes) timeout.\n\n"
    "<u>Mature Content 🔞</u>\n"
    "- Promoting explicit content will result in an instant and permanent ban. No appeals.\n\n"
    "<u>Deletion & Queue Management</u>\n"
    "- To delete a LIVE post, forward the message to the bot from either channel.\n"
    "- Sending the word \"delete\" directly to the bot will result in a timeout.\n"
    "- To cancel your PENDING posts that are still in the queue, click 'Clear My Queue' in the menu.\n\n"
    "<u>Subscription/Perks</u>\n"
    "- Optional add-ons to improve bot interaction. Non-refundable.\n"
    "- Clubs/Associations get 2 accounts strictly for club posts. Misuse leads to revocation.\n\n"
    "<u>Developer/Moderator (Dev/Mod)</u>\n"
    "- Any decision made by the Dev and Mod is with their own level of judgement and should not be questioned.\n\n"
    "<u>Banned Words/User</u>\n"
    "- Banned users can appeal to Dev. Mod-requested bans are not open to appeal."
)

TNC_TEXT = (
    "👋 Welcome to Tapah Confession & Marketplace Bot!\n\n"
    "By tapping below, you acknowledge and agree to fully abide by the updated terms, structural rules, "
    "Marketplace guidelines, and strict timeout regulations outlined in our operational guide."
)

global_next_post_time = None
user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {}
user_photo_cooldowns: Dict[int, datetime.datetime] = {} 
auto_reply_pauses: Dict[int, float] = {}
pending_submissions: Dict[int, Dict[str, Any]] = {}

AWAITING_HELP_MESSAGE = 0
action_states: Dict[int, str] = {}

try:
    TOKEN = os.environ.get('BOT_TOKEN')
    SUB_BOT_URL = os.environ.get('SUB_BOT_URL', 'https://t.me/')
    CHANNEL_ID = os.environ.get('CHANNEL_ID')
    OWNER_ID_STR = os.environ.get('OWNER_ID')
    LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')
    MOD_LOG_CHANNEL_ID = os.environ.get('MOD_LOG_CHANNEL_ID') 
    AD_CHANNEL_ID = os.environ.get('AD_CHANNEL_ID')
    if not all([TOKEN, CHANNEL_ID, OWNER_ID_STR, LOG_CHANNEL_ID, MOD_LOG_CHANNEL_ID, AD_CHANNEL_ID]): sys.exit(1)
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    sys.exit(1)

def load_banned_words() -> Set[str]:
    words = set()
    try:
        if os.path.exists("banned_words.txt"):
            with open("banned_words.txt", "r", encoding="utf-8") as f:
                words = {line.strip().lower() for line in f if line.strip()}
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
                        if float(timestamp) > time.time():
                            timeouts[uid] = {'expiry': timestamp, 'reason': reason}
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
            with open("moderators.txt", "r", encoding="utf-8") as f:
                mods = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return mods

def load_agreed_users() -> Set[int]:
    users = set()
    try:
        if os.path.exists("agreed_users_v2.txt"):
            with open("agreed_users_v2.txt", "r", encoding="utf-8") as f:
                users = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return users

def save_agreed_user(uid):
    users = load_agreed_users()
    if uid not in users:
        with open("agreed_users_v2.txt", "a", encoding="utf-8") as f: f.write(f"{uid}\n")

def load_known_users() -> Set[int]:
    ids = set()
    try:
        if os.path.exists("users.txt"):
            with open("users.txt", "r", encoding="utf-8") as f:
                ids = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return ids

def save_user(uid):
    users = load_known_users()
    if uid not in users:
        with open("users.txt", "a", encoding="utf-8") as f: f.write(f"{uid}\n")

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

def load_autoreply_settings():
    global AUTO_REPLY_ENABLED, AUTO_REPLY_TEXT
    try:
        if os.path.exists("autoreply_status.txt"):
            with open("autoreply_status.txt", "r", encoding="utf-8") as f:
                AUTO_REPLY_ENABLED = f.read().strip() == "True"
        if os.path.exists("autoreply_text.txt"):
            with open("autoreply_text.txt", "r", encoding="utf-8") as f:
                AUTO_REPLY_TEXT = f.read().strip()
    except: pass

def save_autoreply_settings():
    with open("autoreply_status.txt", "w", encoding="utf-8") as f: f.write(str(AUTO_REPLY_ENABLED))
    with open("autoreply_text.txt", "w", encoding="utf-8") as f: f.write(AUTO_REPLY_TEXT)

load_autoreply_settings()

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

def get_active_perks(uid: int) -> Set[str]:
    active_perks = set()
    try:
        if os.path.exists("active_perks.txt"):
            with open("active_perks.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        user_str, perk_type, expiry_str = line.strip().split(',')
                        if int(user_str) == uid and float(expiry_str) > time.time(): active_perks.add(perk_type)
    except: pass
    return active_perks

def append_post_history(message_id: int, user_id: int, is_immune: bool):
    with open("post_history.txt", "a", encoding="utf-8") as f:
        f.write(f"{message_id},{user_id},{1 if is_immune else 0}\n")

def query_post_history(message_id: int) -> Dict[str, Any]:
    try:
        if os.path.exists("post_history.txt"):
            with open("post_history.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        msg_id, uid, immune_flag = line.strip().split(',')
                        if int(msg_id) == message_id:
                            return {'user_id': int(uid), 'is_immune': int(immune_flag) == 1}
    except: pass
    return {'user_id': None, 'is_immune': False}

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def is_owner_or_mod(uid: int) -> bool:
    return uid == OWNER_ID or uid in load_moderators()

async def log_admin_action(context: ContextTypes.DEFAULT_TYPE, action_type: str, executor, target_id: int, reason: str, duration: str = None):
    executor_name = html.escape(str(getattr(executor, 'first_name', 'System')))
    executor_uid = getattr(executor, 'id', 'System')
    raw_user = getattr(executor, 'username', None)
    executor_user = f"@{html.escape(raw_user)}" if raw_user else "No username"

    owner_log = (
        f"🛡️ <b>ADMIN ACTION: {action_type.upper()}</b>\n\n"
        f"👤 <b>Target User ID:</b> <code>{target_id}</code>\n"
        f"👮 <b>Executed By:</b> {executor_name} (<code>{executor_uid}</code> | {executor_user})\n"
    )
    if duration:
        owner_log += f"⏳ <b>Duration:</b> {duration}\n"
    owner_log += f"📝 <b>Reason:</b> {html.escape(reason)}"

    mod_log = (
        f"🛡️ <b>MODERATION ACTION: {action_type.upper()}</b>\n\n"
        f"👤 <b>Target User ID:</b> <code>{target_id}</code>\n"
        f"👮 <b>Executed By:</b> <code>{executor_uid}</code>\n"
    )
    if duration:
        mod_log += f"⏳ <b>Duration:</b> {duration}\n"
    mod_log += f"📝 <b>Reason:</b> {html.escape(reason)}"

    try:
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=owner_log, parse_mode='HTML')
    except Exception as e:
        print(f"Failed to send owner admin log: {e}")

    try:
        await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=mod_log, parse_mode='HTML')
    except Exception as e:
        print(f"Failed to send mod admin log: {e}")

async def is_user_restricted(user_id: int, update: Update=None, context: ContextTypes.DEFAULT_TYPE=None) -> bool:
    if is_owner_or_mod(user_id): return False 
    
    banned_users = load_banned_users()
    if user_id in banned_users:
        msg = f"🚫 You are permanently banned.\n<b>Reason:</b> {html.escape(banned_users[user_id])}"
        if update: await update.message.reply_text(msg, parse_mode='HTML')
        elif context: await context.bot.send_message(user_id, msg, parse_mode='HTML')
        return True
        
    timeouts = load_timeouts()
    if user_id in timeouts:
        expiry = timeouts[user_id]['expiry']
        reason = timeouts[user_id]['reason']
        remaining = expiry - time.time()
        if remaining > 0:
            formatted_rem = format_duration(remaining)
            msg = f"⏳ You are in timeout. Please wait another {formatted_rem}.\n<b>Reason:</b> {html.escape(reason)}"
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
    current_hour = now.hour
    if START_HOUR <= current_hour or current_hour < END_HOUR: return True
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
    category = job_info.get('category', 'Confession')
    
    log_message = (
        f"<b>New {content_type} {category} Log</b>\n\n"
        f"<b>User ID:</b> <code>{safe_uid}</code>\n"
        f"<b>Type:</b> {category}\n"
        f"<b>Name:</b> {safe_name}\n"
        f"<b>Username:</b> {display_username}\n\n"
    )
    content_to_log = text_content or job_info.get('caption')
    if content_to_log: log_message += f"<b>Content:</b>\n{html.escape(content_to_log)}"
    return log_message

def create_mod_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    safe_uid = html.escape(str(job_info['user_id']))
    category = job_info.get('category', 'Confession')
    log_message = (
        f"<b>New {content_type} {category} Log (Moderator View)</b>\n\n"
        f"<b>User ID:</b> <code>{safe_uid}</code>\n"
        f"<b>Type:</b> {category}\n\n"
    )
    content_to_log = text_content or job_info.get('caption')
    if content_to_log: log_message += f"<b>Content:</b>\n{html.escape(content_to_log)}"
    
    if category == "Advertisement":
        log_message += f"\n\n<i>Mod Tip: If this is a confession in the Ad channel, timeout for 1 week using:</i>\n<code>/timeout {safe_uid} 10080 Posted confession in Ad channel</code>\n"
    elif category == "Confession":
        log_message += f"\n\n<i>Mod Tip: If this is an ad in the Confession channel, timeout for 1 week using:</i>\n<code>/timeout {safe_uid} 10080 Posted ad in Confession channel</code>\n"
        
    return log_message

def get_tnc_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Read Guide", callback_data='tc_guide')],
        [InlineKeyboardButton("✅ I Agree", callback_data='tc_agree')]
    ])

def get_main_menu(user_id: int):
    keyboard = []
    if is_owner(user_id):
        role_title = "👑 Owner Panel"
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data='menu_stats'), InlineKeyboardButton("📈 Insights", callback_data='menu_insights')],
            [InlineKeyboardButton("⏰ Active Time", callback_data='menu_active_time'), InlineKeyboardButton("🤖 Auto-Reply", callback_data='menu_autoreply')],
            [InlineKeyboardButton("📜 T&C Stats", callback_data='menu_tnc_stats'), InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words')],
            [InlineKeyboardButton("👮‍♂️ Manage Mods", callback_data='menu_manage_mods'), InlineKeyboardButton("🚫 Manage Bans", callback_data='menu_manage_bans')],
            [InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts'), InlineKeyboardButton("🔗 Toggle Links", callback_data='menu_toggle_links')],
            [InlineKeyboardButton("📸 Toggle Photos", callback_data='menu_toggle_photos'), InlineKeyboardButton("🛒 Subscriptions", url=SUB_BOT_URL)],
            [InlineKeyboardButton("👤 My Status", callback_data='menu_my_status'), InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide')],
            [InlineKeyboardButton("🗑️ Clear My Queue", callback_data='menu_clear'), InlineKeyboardButton("🗑️ Clear Global Queue", callback_data='menu_clear_global')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    elif is_owner_or_mod(user_id):
        role_title = "👮‍♂️ Moderator Panel"
        keyboard = [
            [InlineKeyboardButton("📈 Insights", callback_data='menu_insights'), InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts')],
            [InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words'), InlineKeyboardButton("🛒 Subscriptions", url=SUB_BOT_URL)],
            [InlineKeyboardButton("👤 My Status", callback_data='menu_my_status'), InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide')],
            [InlineKeyboardButton("🗑️ Clear My Queue", callback_data='menu_clear'), InlineKeyboardButton("🗑️ Clear Global Queue", callback_data='menu_clear_global')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    else:
        role_title = "User"
        keyboard = [
            [InlineKeyboardButton("🛒 Subscriptions", url=SUB_BOT_URL)],
            [InlineKeyboardButton("👤 My Status", callback_data='menu_my_status'), InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide')],
            [InlineKeyboardButton("🗑️ Clear My Queue", callback_data='menu_clear'), InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    return role_title, InlineKeyboardMarkup(keyboard)

async def post_text(context: ContextTypes.DEFAULT_TYPE):
    job_info = context.job.data
    try:
        msg = await context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'], read_timeout=20)
        append_post_history(msg.message_id, job_info['user_id'], job_info['is_immune'])
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=create_log_message(job_info, "Text", job_info['text']), parse_mode='HTML', read_timeout=20)
        await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=create_mod_log_message(job_info, "Text", job_info['text']), parse_mode='HTML', read_timeout=20)
    except Exception as e: print(f"Post Error: {e}")

async def post_photo(context: ContextTypes.DEFAULT_TYPE):
    job_info = context.job.data
    try:
        msg = await context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'], read_timeout=30)
        append_post_history(msg.message_id, job_info['user_id'], job_info['is_immune'])
        await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=create_log_message(job_info, "Photo"), parse_mode='HTML', read_timeout=30)
        await context.bot.send_photo(chat_id=MOD_LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=create_mod_log_message(job_info, "Photo"), parse_mode='HTML', read_timeout=30)
    except Exception as e: print(f"Post Error: {e}")

async def group_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not AUTO_REPLY_ENABLED: return
    msg = update.message
    if not msg or not msg.from_user: return
    raw_msg = msg.to_dict()
    is_channel_dm = raw_msg.get('chat', {}).get('is_direct_messages', False)
    if not is_channel_dm: return

    chat_id = msg.chat_id
    now = time.time()

    if str(msg.from_user.id) == str(OWNER_ID):
        auto_reply_pauses[chat_id] = now + AUTO_REPLY_PAUSE_DURATION
        return

    if chat_id in auto_reply_pauses:
        if now < auto_reply_pauses[chat_id]:
            return  
        else:
            del auto_reply_pauses[chat_id]  

    try: await msg.reply_text(AUTO_REPLY_TEXT)
    except Exception: pass


async def _schedule_post_direct(user, context: ContextTypes.DEFAULT_TYPE, submission: Dict[str, Any], post_category: str, target_chat_id: str):
    global global_next_post_time
    user_id = user.id
    is_privileged = is_owner_or_mod(user_id)
    
    if await is_user_restricted(user_id, context=context): return

    post_type = submission['type']
    text_to_check = submission['text']
    
    current_tier = get_user_tier(user_id)
    active_perks = get_active_perks(user_id)
    cfg = TIER_CONFIG[current_tier]

    if post_type == 'photo':
        if not PHOTOS_ENABLED and not is_privileged:
            await context.bot.send_message(user_id, "❌ Photo posts are currently disabled.")
            return
        if not is_privileged:
            now = datetime.datetime.now()
            last_photo = user_photo_cooldowns.get(user_id)
            if last_photo and (now - last_photo).total_seconds() < cfg['photo_cooldown']:
                rem = cfg['photo_cooldown'] - (now - last_photo).total_seconds()
                await context.bot.send_message(user_id, f"⏳ Photos limited to once every {format_duration(cfg['photo_cooldown'])}. Please wait {format_duration(rem)}.")
                return
            user_photo_cooldowns[user_id] = now

    if check_for_banned_words(text_to_check) and not is_privileged:
        await context.bot.send_message(user_id, "❌ Your message contains words that are not allowed.")
        return

    if contains_link_text(text_to_check):
        if not LINKS_ENABLED and not is_privileged:
            await context.bot.send_message(user_id, "❌ Link sharing is currently disabled.")
            return
        if not is_privileged:
            now = datetime.datetime.now()
            last_link = user_link_cooldowns.get(user_id)
            if last_link and (now - last_link).total_seconds() < cfg['link_cooldown']:
                rem = cfg['link_cooldown'] - (now - last_link).total_seconds()
                await context.bot.send_message(user_id, f"⏳ Links limited to once every {format_duration(cfg['link_cooldown'])}. Please wait {format_duration(rem)}.")
                return
            user_link_cooldowns[user_id] = now

    now_tz = datetime.datetime.now(TIMEZONE)
    base_delay = 0
    if not is_bot_active() and not is_privileged:
        base_delay = get_seconds_until_active()
        
    if global_next_post_time is None or global_next_post_time < now_tz:
        global_next_post_time = now_tz

    if is_privileged or 'spotlight' in active_perks:
        final_delay = 0 
        scheduled_time = now_tz
    else:
        wake_time = now_tz + datetime.timedelta(seconds=base_delay)
        queue_start = max(now_tz, global_next_post_time, wake_time)
        
        queue_duration = cfg['personal_queue_duration']
        scheduled_time = queue_start + datetime.timedelta(seconds=queue_duration)
        
        global_next_post_time = scheduled_time
        final_delay = (scheduled_time - now_tz).total_seconds()
    
    job_context = {
        'chat_id': target_chat_id, 
        'user_id': user.id, 
        'user_name': user.first_name, 
        'username': user.username, 
        'is_immune': 'immunity' in active_perks,
        'category': post_category
    }
    
    if post_type == 'text':
        job_context['text'] = text_to_check
        context.job_queue.run_once(post_text, final_delay, data=job_context, name=str(user_id))
    else:
        job_context['photo'] = submission['photo']
        job_context['caption'] = text_to_check
        context.job_queue.run_once(post_photo, final_delay, data=job_context, name=str(user_id))

    if final_delay == 0:
        await context.bot.send_message(user_id, f"✅ {post_category} sent instantly!")
    elif base_delay == 0 and final_delay > 0:
        est_time_str = scheduled_time.strftime('%I:%M:%S %p')
        await context.bot.send_message(
            user_id,
            f"🕒 <b>{post_category} Queued!</b>\n"
            f"Wait Time: <b>{format_duration(final_delay)}</b>\n"
            f"Estimated Post Time: <b>{est_time_str}</b>\n\n"
            f"💡 <i>Want a better experience? Skip the queue or reduce your wait time by subscribing at {SUB_BOT_URL}</i>",
            parse_mode='HTML'
        )
    else:
        est_time_str = scheduled_time.strftime('%I:%M:%S %p')
        await context.bot.send_message(user_id, f"🌙 Bot is currently in sleep mode. Your {post_category.lower()} is queued for {est_time_str}.")

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

    is_channel = (target_chat == str(CHANNEL_ID) or f"@{CHANNEL_ID.lstrip('@')}" == target_chat)
    is_ad_channel = (target_chat == str(AD_CHANNEL_ID) or f"@{AD_CHANNEL_ID.lstrip('@')}" == target_chat)

    if is_channel or is_ad_channel:
        actual_target_chat = CHANNEL_ID if is_channel else AD_CHANNEL_ID
        is_privileged = is_owner_or_mod(user_id)
        now = datetime.datetime.now()
        
        post_record = query_post_history(msg_id)
        current_tier = get_user_tier(user.id)
        cfg = TIER_CONFIG[current_tier]

        if cfg['delete_access'] == 'own' and post_record['user_id'] != user.id and not is_privileged:
            await update.message.reply_text("❌ Access Denied. Your tier metrics do not match authorship signatures.")
            return

        if post_record['is_immune'] and not is_privileged:
            await update.message.reply_text("🛡️ This post is covered under active Immunity perks. It cannot be deleted.")
            return

        if not is_privileged:
            last_del = user_delete_cooldowns.get(user_id)
            if last_del and (now - last_del).total_seconds() < cfg['delete_cooldown']:
                rem = cfg['delete_cooldown'] - (now - last_del).total_seconds()
                await update.message.reply_text(f"⏳ Please wait {format_duration(rem)} before deleting again.")
                return

        try:
            await context.bot.delete_message(chat_id=actual_target_chat, message_id=msg_id)
            if not is_privileged: user_delete_cooldowns[user_id] = now
            await update.message.reply_text("🗑 Message successfully deleted from channel.")
            
            content = update.message.text or update.message.caption or "[Media with no caption]"
            raw_username = user.username
            display_username = f"@{html.escape(raw_username)}" if raw_username else "Not available"
            safe_user = html.escape(str(user.first_name))
            safe_uid = html.escape(str(user_id))
            safe_content = html.escape(content)
            
            owner_log_txt = (
                f"🗑 <b>DELETION LOG</b>\n*By:* {safe_user} (<code>{safe_uid}</code>)\n*Username:* {display_username}\n"
                f"*Msg ID:* <code>{msg_id}</code>\n*Original Content:*\n{safe_content}"
            )
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=owner_log_txt, parse_mode='HTML')

            mod_log_txt = (
                f"🗑 <b>DELETION LOG (Moderator View)</b>\n*By User ID:* <code>{safe_uid}</code>\n"
                f"*Msg ID:* <code>{msg_id}</code>\n*Original Content:*\n{safe_content}"
            )
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
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><user_id></code>\nExample: <code>123456789</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

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
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><user_id></code>\nExample: <code>123456789</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_owner(update.message.from_user.id): return False
    try:
        start_h = int(context.args[0])
        end_h = int(context.args[1])
        if not (0 <= start_h <= 23) or not (0 <= end_h <= 23): raise ValueError
        global START_HOUR, END_HOUR
        START_HOUR, END_HOUR = start_h, end_h
        save_time_settings()
        await update.message.reply_text(f"✅ Active time updated!\nStart: {format_time(START_HOUR)}\nEnd/Sleep: {format_time(END_HOUR)}")
        return True
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><start_hour> <end_hour></code> (0-23)\nExample: <code>21 18</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

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
    if not is_owner(user.id):
        await update.message.reply_text("❌ Only the Owner/Developer can ban users.")
        return False
    try:
        target = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided."
        banned = load_banned_users()
        banned[target] = reason
        with open("banned_users.txt", "w", encoding="utf-8") as f:
            for u, r in banned.items(): f.write(f"{u},{r}\n")
        await update.message.reply_text(f"🚫 User <code>{target}</code> banned.\n<b>Reason:</b> {html.escape(reason)}", parse_mode='HTML')
        await log_admin_action(context, "Ban", user, target, reason)
        return True
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><user_id> <reason></code>\nExample: <code>123456789 Spamming channel</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ Only the Owner/Developer can unban users.")
        return False
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
        else:
            await update.message.reply_text(f"⚠️ User <code>{target}</code> is not in the ban list. Send /cancel to abort.", parse_mode='HTML')
            return False
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><user_id></code>\nExample: <code>123456789</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

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
        
        duration_str = format_duration(minutes * 60)
        await update.message.reply_text(f"⏳ User <code>{target_id}</code> timed out for {duration_str}.", parse_mode='HTML')
        
        str_id = str(target_id)
        masked_id = str_id[:4] + "*" * (len(str_id) - 4)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📢 <b>Timeout Notice</b>\nUser <code>{masked_id}</code> has been timed out for {duration_str}.\n<b>Reason:</b> {html.escape(reason)}",
            parse_mode='HTML'
        )
        await log_admin_action(context, "Timeout", user, target_id, reason, duration_str)
        return True
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><user_id> <minutes> <reason></code>\nExample: <code>123456789 60 Flooding chat</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

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
        else:
            await update.message.reply_text(f"⚠️ User <code>{target_id}</code> is not currently in timeout. Send /cancel to abort.", parse_mode='HTML')
            return False
    except (IndexError, ValueError):
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><user_id></code>\nExample: <code>123456789</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

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
    except IndexError:
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><word></code>\nExample: <code>badword</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

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
    except IndexError:
        await update.message.reply_text("❌ <b>Invalid format.</b> Send: <code><word></code>\nExample: <code>badword</code>\n\nOr send /cancel to abort.", parse_mode='HTML')
        return False

# Clear normal user's OWN queue
async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if await is_user_restricted(user_id, update): return
    
    jobs = context.job_queue.get_jobs_by_name(str(user_id))
    count = len(jobs)
    for job in jobs:
        job.schedule_removal()
        
    await update.message.reply_text(f"✅ Cleared {count} of your pending posts from the queue.")

# Clear global queue (Owner/Mod only)
async def clear_all_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global global_next_post_time
    if not update.message or not update.message.from_user: return
    if not is_owner_or_mod(update.message.from_user.id): 
        await update.message.reply_text("❌ Access Denied.")
        return
        
    global_next_post_time = datetime.datetime.now(TIMEZONE)
    await update.message.reply_text("✅ Global Queue Master Line cleared.")

async def gift_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not is_owner(update.message.from_user.id): return
    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ <b>Format:</b> <code>/gift &lt;user_id&gt; &lt;tier_code&gt; &lt;days&gt;</code>\n"
            "<i>Valid Tiers:</i> <code>tier1</code>, <code>tier2</code>, <code>club</code>\n"
            "<i>Example:</i> <code>/gift 123456789 tier1 14</code>",
            parse_mode='HTML'
        )
        return
    try:
        target_uid = int(context.args[0])
        tier_code = context.args[1].lower()
        days = int(context.args[2])
        
        if tier_code not in TIER_CONFIG or tier_code == 'basic':
            await update.message.reply_text("❌ Invalid tier code. Valid choices: <code>tier1</code>, <code>tier2</code>, <code>club</code>", parse_mode='HTML')
            return
            
        now = time.time()
        expiry = now + (days * 86400)
        
        with open("active_subscriptions.txt", "a", encoding="utf-8") as f:
            f.write(f"{target_uid},{tier_code},{expiry}\n")
            
        tier_name = TIER_CONFIG[tier_code]['name']
        await update.message.reply_text(f"🎁 Successfully gifted <b>{tier_name}</b> ({days} days) to user <code>{target_uid}</code>!", parse_mode='HTML')
        await log_admin_action(context, "Gift Subscription", update.message.from_user, target_uid, f"Gifted {tier_name}", f"{days} days")
        
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"🎁 <b>You've received a gift!</b>\nThe Developer has granted you <b>{tier_name}</b> access for {days} days. Enjoy your premium privileges!",
                parse_mode='HTML'
            )
        except Exception as e:
            await update.message.reply_text(f"⚠️ Gift logged, but user couldn't be notified directly: {e}")
    except ValueError:
        await update.message.reply_text("❌ User ID and Days must be valid numbers.")

async def revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not is_owner(update.message.from_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Format: <code>/revoke <user_id> <reason></code>", parse_mode='HTML')
        return
    try:
        target_uid = int(context.args[0])
        reason = " ".join(context.args[1:])
        
        revoked = False
        remaining_lines = []
        if os.path.exists("active_subscriptions.txt"):
            with open("active_subscriptions.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        u_id, tier, expiry = line.strip().split(',')
                        if int(u_id) == target_uid:
                            revoked = True
                        else:
                            remaining_lines.append(line)
                            
        if revoked:
            with open("active_subscriptions.txt", "w", encoding="utf-8") as f:
                f.writelines(remaining_lines)
            
            await update.message.reply_text(f"✅ Subscription for user <code>{target_uid}</code> has been REVOKED.", parse_mode='HTML')
            await log_admin_action(context, "Revoke Subscription", update.message.from_user, target_uid, reason)
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"⚠️ <b>Subscription Revoked</b>\n\nYour subscription has been revoked by the Developer.\n<b>Reason:</b> {html.escape(reason)}",
                    parse_mode='HTML'
                )
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not notify user {target_uid} directly: {e}")
        else:
            await update.message.reply_text(f"⚠️ No active subscription found for user <code>{target_uid}</code>.", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ User ID must be a valid number.")

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
        f"{greeting}Send any text or photo to post it anonymously to the channel.\n\nClick a button below for more options:",
        reply_markup=reply_markup
    )

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LINKS_ENABLED, PHOTOS_ENABLED, AUTO_REPLY_ENABLED 
    query = update.callback_query
    await query.answer() 
    user_id = query.from_user.id

    if query.data in ['submit_confession', 'submit_ad']:
        submission = pending_submissions.get(user_id)
        if not submission:
            await query.edit_message_text("❌ Session expired. Please send your message again.")
            return
        
        post_category = "Confession" if query.data == 'submit_confession' else "Advertisement"
        target_chat_id = CHANNEL_ID if post_category == "Confession" else AD_CHANNEL_ID
        
        if post_category == "Advertisement":
            has_photo = submission['type'] == 'photo'
            text_content = submission['text']
            
            text_nospace = text_content.replace(' ', '').replace('-', '')
            phone_pattern = r'(\+?6?01\d{8,9})'
            has_phone = bool(re.search(phone_pattern, text_nospace))
            has_link = contains_link_text(text_content)
            has_username = '@' in text_content
            
            if not (has_photo or has_phone or has_link or has_username):
                await query.edit_message_text(
                    "❌ <b>Advertisement Rejected</b>\n\n"
                    "Ads MUST contain at least one of the following:\n"
                    "- A photo\n- A web link\n- A phone number\n- A Telegram username (@)\n\n"
                    "Please edit your message and try again.", 
                    parse_mode='HTML'
                )
                del pending_submissions[user_id]
                return
        
        await query.edit_message_text(f"✅ Processing as {post_category}...")
        await _schedule_post_direct(query.from_user, context, submission, post_category, target_chat_id)
        del pending_submissions[user_id]
        return

    elif query.data == 'submit_cancel':
        if user_id in pending_submissions:
            del pending_submissions[user_id]
        await query.edit_message_text("❌ Submission cancelled.")
        return

    if query.data == 'tc_agree':
        save_agreed_user(user_id)
        role_title, reply_markup = get_main_menu(user_id)
        greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
        await query.edit_message_text(
            f"✅ Thank you for agreeing to the Terms and Conditions!\n\n{greeting}Send any text or photo to post it anonymously to the channel.\n\nClick a button below for more options:",
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
        await query.edit_message_text(f"{greeting}Send any text or photo to post it anonymously to the channel.\n\nClick a button below for more options:", reply_markup=reply_markup)
    elif query.data == 'menu_guide':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=GUIDE_TEXT, parse_mode='HTML', reply_markup=markup)
        
    elif query.data == 'menu_clear':
        jobs = context.job_queue.get_jobs_by_name(str(user_id))
        count = len(jobs)
        for job in jobs:
            job.schedule_removal()
        await query.edit_message_text(text=f"✅ Cleared {count} of your pending posts from the queue.")
        
    elif query.data == 'menu_clear_global':
        if not is_owner_or_mod(user_id): return
        global global_next_post_time
        global_next_post_time = datetime.datetime.now(TIMEZONE)
        await query.edit_message_text(text="✅ Global Queue Master Line has been reset to zero.")
        
    elif query.data == 'menu_close':
        if user_id in action_states: del action_states[user_id]
        await query.edit_message_text(text="👋 Menu closed. Send a message or photo to confess.")
        
    elif query.data == 'menu_my_status':
        tier = get_user_tier(user_id)
        perks = get_active_perks(user_id)
        
        perk_names = [PERK_CONFIG[p]['name'] for p in perks if p in PERK_CONFIG]
        perk_str = ", ".join(perk_names) if perk_names else "None"
        cfg = TIER_CONFIG[tier]
        
        txt = (
            f"👤 <b>Runtime Profile Audit</b>\n\n"
            f"🎫 <b>Owned Access Tier:</b> <code>{cfg['name']}</code>\n"
            f"⚡ <b>Owned Active Perks:</b> <code>{perk_str}</code>\n\n"
            f"📊 <b>Active Tier Privileges:</b>\n"
            f"• Personal Queue Duration: <code>{format_duration(cfg['personal_queue_duration'])}</code>\n"
            f"• Photo/Link Limit: <code>{format_duration(cfg['photo_cooldown'])}</code>\n"
            f"• Deletion Access: <code>{cfg['delete_access'].title()} posts</code>\n"
            f"• Deletion Cooldown: <code>{format_duration(cfg['delete_cooldown'])}</code>"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_insights':
        if not is_owner_or_mod(user_id): return
        now_tz = datetime.datetime.now(TIMEZONE)
        global_wait = max(0, (global_next_post_time - now_tz).total_seconds()) if global_next_post_time else 0
        
        lines = ["📈 <b>Queue Insights (Current Wait Times)</b>\n"]
        for tier_code, cfg in TIER_CONFIG.items():
            tier_wait = global_wait + cfg['personal_queue_duration']
            lines.append(f"• <b>{cfg['name']}:</b> {format_duration(tier_wait)}")
        
        lines.append(f"\n<i>*Wait times include the global queue delay ({format_duration(global_wait)}) plus the tier's personal queue duration.</i>")
        
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text="\n".join(lines), parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_stats':
        if not is_owner(user_id): return
        uptime_str = str(datetime.datetime.now() - BOT_START_TIME).split('.')[0] 
        msg = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{len(load_known_users())}</code>\n"
            f"✅ <b>Agreed Users (V2):</b> <code>{len(load_agreed_users())}</code>\n"
            f"🚫 <b>Banned Users:</b> <code>{len(load_banned_users())}</code>\n"
            f"👮‍♂️ <b>Moderators:</b> <code>{len(load_moderators())}</code>\n"
            f"⏳ <b>Uptime:</b> <code>{uptime_str}</code>\n\n"
            f"<b>Feature Status:</b>\n"
            f"🔗 Links: {'✅ Enabled' if LINKS_ENABLED else '❌ Disabled'}\n"
            f"📸 Photos: {'✅ Enabled' if PHOTOS_ENABLED else '❌ Disabled'}\n"
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
            f"✅ <b>Agreed (V2):</b> <code>{agreed_users}</code>\n"
            f"⏳ <b>Pending Agreement:</b> <code>{pending_users}</code>\n\n"
            f"<i>Note: Users in the 'Pending' list cannot send confessions or use the bot until they click 'I Agree' to the new rules.</i>"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=msg, parse_mode='HTML', reply_markup=markup)
        
    elif query.data == 'menu_toggle_links':
        if not is_owner(user_id): return
        LINKS_ENABLED = not LINKS_ENABLED
        status = 'ENABLED' if LINKS_ENABLED else 'DISABLED'
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=f"🔗 Link restriction is now {'OFF' if LINKS_ENABLED else 'ON'}.", reply_markup=markup)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 Notice: Link sharing has been {status} by the administrator.")

    elif query.data == 'menu_toggle_photos':
        if not is_owner(user_id): return
        PHOTOS_ENABLED = not PHOTOS_ENABLED
        status = 'ENABLED' if PHOTOS_ENABLED else 'DISABLED'
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=f"📸 Photo posts are now {'ENABLED' if PHOTOS_ENABLED else 'DISABLED'}.", reply_markup=markup)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 Notice: Photo confessions have been {status} by the administrator.")

    elif query.data == 'menu_autoreply':
        if not is_owner(user_id): return
        status = "✅ Enabled" if AUTO_REPLY_ENABLED else "❌ Disabled"
        txt = f"🤖 <b>Auto-Reply Management</b>\n\n<b>Current Status:</b> {status}\n\n<b>Current Auto-Reply Message:</b>\n<code>{html.escape(AUTO_REPLY_TEXT)}</code>\n\nChoose an action below:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit Message", callback_data='trig_setautoreply'), InlineKeyboardButton("🔄 Toggle Status", callback_data='toggle_autoreply_btn')],
            [InlineKeyboardButton("◀️ Back", callback_data='menu_back')]
        ])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'toggle_autoreply_btn':
        if not is_owner(user_id): return
        AUTO_REPLY_ENABLED = not AUTO_REPLY_ENABLED
        save_autoreply_settings()
        status = "✅ Enabled" if AUTO_REPLY_ENABLED else "❌ Disabled"
        txt = f"🤖 <b>Auto-Reply Management</b>\n\n<b>Current Status:</b> {status}\n\n<b>Current Auto-Reply Message:</b>\n<code>{html.escape(AUTO_REPLY_TEXT)}</code>\n\nChoose an action below:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit Message", callback_data='trig_setautoreply'), InlineKeyboardButton("🔄 Toggle Status", callback_data='toggle_autoreply_btn')],
            [InlineKeyboardButton("◀️ Back", callback_data='menu_back')]
        ])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

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
        if query.data in ['trig_ban', 'trig_unban', 'trig_addword', 'trig_rmword', 'trig_addmod', 'trig_rmmod', 'trig_settime', 'trig_setautoreply'] and not is_owner(user_id):
            await query.edit_message_text("❌ Only the Owner/Developer can perform this action.")
            return

        action_states[user_id] = query.data
        prompts = {
            'trig_ban': "🔨 <b>Ban User</b>\nPlease send the target User ID and Reason.\n<i>Example:</i> <code>123456789 Spamming</code>\n\nType /cancel to abort.",
            'trig_unban': "✅ <b>Unban User</b>\nPlease send the target User ID to unban.\n<i>Example:</i> <code>123456789</code>\n\nType /cancel to abort.",
            'trig_timeout': "⏱️ <b>Timeout User</b>\nPlease send the User ID, Minutes, and Reason.\n<i>Example:</i> <code>123456789 60 Flooding chat</code>\n\nType /cancel to abort.",
            'trig_rmtimeout': "✅ <b>Remove Timeout</b>\nPlease send the target User ID to remove timeout.\n<i>Example:</i> <code>123456789</code>\n\nType /cancel to abort.",
            'trig_addmod': "➕ <b>Add Moderator</b>\nPlease send the User ID to promote.\n<i>Example:</i> <code>123456789</code>\n\nType /cancel to abort.",
            'trig_rmmod': "➖ <b>Remove Moderator</b>\nPlease send the User ID to demote.\n<i>Example:</i> <code>123456789</code>\n\nType /cancel to abort.",
            'trig_addword': "➕ <b>Add Banned Word</b>\nPlease send the word you want to ban.\n<i>Example:</i> <code>badword</code>\n\nType /cancel to abort.",
            'trig_rmword': "➖ <b>Remove Banned Word</b>\nPlease send the word you want to unban.\n<i>Example:</i> <code>badword</code>\n\nType /cancel to abort.",
            'trig_settime': "✏️ <b>Set Active Time</b>\nPlease send the Start and End hours (24h format).\n<i>Example for 9PM to 6PM:</i> <code>21 18</code>\n\nType /cancel to abort.",
            'trig_setautoreply': "✏️ <b>Set Auto-Reply</b>\nPlease send the new auto-reply message you want the bot to say.\n\nType /cancel to abort."
        }
        cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='menu_back')]])
        await query.edit_message_text(text=prompts.get(query.data, "Please provide input. Type /cancel to abort."), parse_mode='HTML', reply_markup=cancel_markup)

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if user_id not in load_agreed_users() and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return

    if user_id in action_states:
        state = action_states[user_id]
        context.args = update.message.text.split()
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
        elif state == 'trig_setautoreply': 
            global AUTO_REPLY_TEXT
            AUTO_REPLY_TEXT = update.message.text
            save_autoreply_settings()
            await update.message.reply_text("✅ Auto-reply message updated successfully!")
            success = True
            
        if success:
            del action_states[user_id]
        return

    text_stripped = update.message.text.strip()
    
    if text_stripped.lower() == 'delete':
        is_privileged = is_owner_or_mod(user_id)
        if not is_privileged:
            expiry_time = time.time() + 60
            timeouts = load_timeouts()
            timeouts[user_id] = {'expiry': expiry_time, 'reason': "Invalid deletion attempt."}
            save_timeouts_to_disk(timeouts)
            await update.message.reply_text(f"⚠️ <b>Timeout Applied (1 Minute)</b>\n\nYou typed 'delete'. To delete a confession, you must forward the actual message from the channel here.\n\n{GUIDE_TEXT}", parse_mode='HTML')
            str_id = str(user_id)
            masked_id = str_id[:4] + "*" * (len(str_id) - 4)
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"📢 <b>Timeout Notice</b>\nUser <code>{masked_id}</code> has been timed out for 1m.\n<b>Reason:</b> Invalid deletion attempt.",
                parse_mode='HTML'
            )
            await log_admin_action(context, "Timeout (Auto)", "System", user_id, "Invalid deletion attempt ('delete')", "1 minute")
            return
        else:
            await update.message.reply_text("To delete a post, you need to forward the message from the channel. Just typing 'delete' does not work.")
            return

    pending_submissions[user_id] = {
        'type': 'text',
        'text': text_stripped,
        'photo': None
    }
    keyboard = [
        [InlineKeyboardButton("🗣️ Submit as Confession", callback_data="submit_confession")],
        [InlineKeyboardButton("🛒 Submit as Advertisement", callback_data="submit_ad")],
        [InlineKeyboardButton("❌ Cancel", callback_data="submit_cancel")]
    ]
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
    pending_submissions[user_id] = {
        'type': 'photo',
        'text': text_stripped,
        'photo': update.message.photo[-1].file_id
    }
    keyboard = [
        [InlineKeyboardButton("🗣️ Submit as Confession", callback_data="submit_confession")],
        [InlineKeyboardButton("🛒 Submit as Advertisement", callback_data="submit_ad")],
        [InlineKeyboardButton("❌ Cancel", callback_data="submit_cancel")]
    ]
    await update.message.reply_text("Where would you like to post this photo?", reply_markup=InlineKeyboardMarkup(keyboard))

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError): return
    print(f"Update {update} caused error {context.error}")

async def post_init(application: Application):
    now_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    try:
        await application.bot.send_message(chat_id=OWNER_ID, text=f"✅ Main Bot is up! Running v20+ with Marketplace Setup. Started at {now_str}")
    except Exception: pass

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).read_timeout(30).connect_timeout(30).build()
    
    application.add_error_handler(error_handler)
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={AWAITING_HELP_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, forward_help)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    ))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel)) 
    application.add_handler(CommandHandler("settime", set_time))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("addmod", add_mod))
    application.add_handler(CommandHandler("removemod", remove_mod))
    application.add_handler(CommandHandler("timeout", timeout_user))
    application.add_handler(CommandHandler("untimeout", remove_timeout))
    application.add_handler(CommandHandler("addban", add_banned_word))
    application.add_handler(CommandHandler("removeban", remove_banned_word))
    application.add_handler(CommandHandler("clearqueue", clear_queue))
    application.add_handler(CommandHandler("clearallqueue", clear_all_queue))
    application.add_handler(CommandHandler("revoke", revoke_subscription))
    application.add_handler(CommandHandler("gift", gift_subscription))

    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern='^(menu_|trig_|toggle_|tc_|submit_)'))
    application.add_handler(MessageHandler(filters.FORWARDED, handle_delete))
    application.add_handler(MessageHandler((filters.ChatType.SUPERGROUP | filters.ChatType.GROUPS) & ~filters.COMMAND, group_auto_reply))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo_input))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_input))

    print("--- Main Confession Bot is Online ---")
    application.run_polling()

if __name__ == '__main__':
    main()
