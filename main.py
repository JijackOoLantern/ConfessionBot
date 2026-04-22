import os
import sys
import datetime
import time
import re
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    MessageHandler,
    Filters,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
)
from telegram.error import BadRequest, TelegramError, Unauthorized, NetworkError
from telegram.utils.helpers import escape_markdown
from typing import Set, Dict, Any, Union
import pytz

# --- Google Sheets Imports ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Load .env file for local testing (VS Code)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Bot's Memory and Settings ---
POST_DELAY = 15  
DELETE_COOLDOWN = 60  
LINK_COOLDOWN = 14400 
PHOTO_COOLDOWN = 14400 
TIMEZONE = pytz.timezone('Asia/Kuala_Lumpur') 

BOT_START_TIME = datetime.datetime.now()

# Active Hours (Default 24h format, can be overridden by file)
START_HOUR = 21  # 21:00 (9:00 PM)
END_HOUR = 18    # 18:00 (6:00 PM Next day)

LINKS_ENABLED = True
PHOTOS_ENABLED = True

user_queues: Dict[int, datetime.datetime] = {}
user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {}
user_photo_cooldowns: Dict[int, datetime.datetime] = {} 

AWAITING_HELP_MESSAGE = 0

# --- Environment Variable Loading & Validation ---
try:
    TOKEN = os.environ.get('BOT_TOKEN')
    CHANNEL_ID = os.environ.get('CHANNEL_ID')
    OWNER_ID_STR = os.environ.get('OWNER_ID')
    LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')
    MOD_LOG_CHANNEL_ID = os.environ.get('MOD_LOG_CHANNEL_ID') 
    GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME', 'ConfessionLogs') 

    if not all([TOKEN, CHANNEL_ID, OWNER_ID_STR, LOG_CHANNEL_ID, MOD_LOG_CHANNEL_ID]):
        missing = [k for k, v in {
            'BOT_TOKEN': TOKEN, 
            'CHANNEL_ID': CHANNEL_ID, 
            'OWNER_ID': OWNER_ID_STR, 
            'LOG_CHANNEL_ID': LOG_CHANNEL_ID,
            'MOD_LOG_CHANNEL_ID': MOD_LOG_CHANNEL_ID
        }.items() if not v]
        print(f"❌ CRITICAL ERROR: Missing .env variables: {', '.join(missing)}")
        sys.exit(1)
    
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    print("❌ CRITICAL ERROR: OWNER_ID must be a number in your .env file.")
    sys.exit(1)

# --- Persistence Loading ---

def load_ids(filename):
    ids = set()
    try:
        if os.path.exists(filename):
            with open(filename, "r") as f:
                ids = {int(line.strip()) for line in f if line.strip().isdigit()}
        else:
            open(filename, "a").close()
    except Exception as e:
        print(f"Warning: Could not load {filename}: {e}")
    return ids

KNOWN_USERS = load_ids("users.txt")
MODERATORS = load_ids("moderators.txt") 

# 1. Load Time Settings (NEW)
def load_time_settings():
    global START_HOUR, END_HOUR
    try:
        if os.path.exists("active_time.txt"):
            with open("active_time.txt", "r") as f:
                parts = f.read().strip().split(',')
                START_HOUR = int(parts[0])
                END_HOUR = int(parts[1])
    except Exception as e:
        print(f"Warning: Could not load active_time.txt. Using defaults.")

def save_time_settings():
    with open("active_time.txt", "w") as f:
        f.write(f"{START_HOUR},{END_HOUR}")

load_time_settings() # Call immediately

# 2. Banned Users with Reasons (UPDATED)
BANNED_USERS: Dict[int, str] = {}
try:
    if os.path.exists("banned_users.txt"):
        with open("banned_users.txt", "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split(',', 1) # Split only on the first comma
                uid = int(parts[0])
                reason = parts[1] if len(parts) > 1 else "No reason provided."
                BANNED_USERS[uid] = reason
    else:
        open("banned_users.txt", "a").close()
except Exception as e:
    print(f"Warning: Could not load banned_users.txt: {e}")

# 3. Timeouts with Reasons (UPDATED)
USER_TIMEOUTS: Dict[int, Dict[str, Union[float, str]]] = {}
try:
    with open("timeouts.txt", "r") as f:
        for line in f:
            if "," in line:
                parts = line.strip().split(',', 2) # Split UID, Timestamp, Reason
                uid = int(parts[0])
                timestamp = float(parts[1])
                reason = parts[2] if len(parts) > 2 else "No reason provided."
                if float(timestamp) > datetime.datetime.now().timestamp():
                    USER_TIMEOUTS[int(uid)] = {'expiry': timestamp, 'reason': reason}
except FileNotFoundError:
    open("timeouts.txt", "a").close()

# 4. Banned Words
BANNED_WORDS: Set[str] = set()
try:
    if os.path.exists("banned_words.txt"):
        with open("banned_words.txt", "r") as f:
            BANNED_WORDS = {line.strip().lower() for line in f if line.strip()}
    else:
        open("banned_words.txt", "a").close()
except Exception as e:
    print(f"Warning: Could not load banned_words.txt: {e}")

# --- Google Sheets Setup ---
SHEET_CLIENT = None

def init_google_sheets():
    global SHEET_CLIENT
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if not os.path.exists("google_credentials.json"):
            print("⚠️ google_credentials.json not found. Google Sheets logging will be disabled.")
            return
        creds = ServiceAccountCredentials.from_json_keyfile_name("google_credentials.json", scope)
        SHEET_CLIENT = gspread.authorize(creds)
        print("✅ Google Sheets Connected Successfully.")
    except Exception as e:
        print(f"❌ Failed to connect to Google Sheets: {e}")

def log_to_gsheet(job_info, text_content=None, photo_id=None):
    if not SHEET_CLIENT: return
    try:
        sheet = SHEET_CLIENT.open(GOOGLE_SHEET_NAME).sheet1
        now = datetime.datetime.now(TIMEZONE)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        user_id = str(job_info['user_id'])
        username = f"@{job_info.get('username')}" if job_info.get('username') else "N/A"
        content = text_content or job_info.get('caption') or "[No Text]"
        photo_ref = photo_id if photo_id else "N/A"
        sheet.append_row([date_str, time_str, user_id, username, content, photo_ref])
    except Exception as e:
        print(f"⚠️ Error logging to Google Sheet: {e}")

# --- Helper Functions ---

def is_owner_or_mod(uid):
    return uid == OWNER_ID or uid in MODERATORS

def is_owner(uid): 
    return uid == OWNER_ID

def save_timeouts():
    with open("timeouts.txt", "w") as f:
        for uid, data in USER_TIMEOUTS.items():
            if data['expiry'] > datetime.datetime.now().timestamp():
                f.write(f"{uid},{data['expiry']},{data['reason']}\n")

def is_user_restricted(user_id, update):
    """Checks if a user is banned or timed out. Replies with reason."""
    if is_owner_or_mod(user_id):
        return False 
        
    # Ban Check
    if user_id in BANNED_USERS:
        reason = BANNED_USERS[user_id]
        update.message.reply_text(f"🚫 You are permanently banned from using this bot.\n\n*Reason:* {reason}", parse_mode='Markdown')
        return True

    # Timeout Check
    if user_id in USER_TIMEOUTS:
        expiry = USER_TIMEOUTS[user_id]['expiry']
        reason = USER_TIMEOUTS[user_id]['reason']
        remaining = expiry - datetime.datetime.now().timestamp()
        
        if remaining > 0:
            minutes_left = int(remaining / 60) + 1
            update.message.reply_text(f"⏳ You are in timeout. You cannot use the bot for another {minutes_left} minutes.\n\n*Reason:* {reason}", parse_mode='Markdown')
            return True
        else:
            del USER_TIMEOUTS[user_id]
            save_timeouts()
            
    return False

def format_time(hour_24):
    """Formats 24h integer to 12h AM/PM string"""
    am_pm = "AM" if hour_24 < 12 else "PM"
    h = hour_24 if hour_24 <= 12 else hour_24 - 12
    if h == 0: h = 12
    return f"{h:02d}:00 {am_pm}"

def is_bot_active():
    now = datetime.datetime.now(TIMEZONE)
    current_hour = now.hour
    if START_HOUR <= current_hour or current_hour < END_HOUR:
        return True
    return False

def get_seconds_until_active():
    now = datetime.datetime.now(TIMEZONE)
    target = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    if now.hour >= START_HOUR:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()

def save_user(uid):
    if uid not in KNOWN_USERS:
        KNOWN_USERS.add(uid)
        with open("users.txt", "a") as f:
            f.write(f"{uid}\n")

def check_for_banned_words(text: str) -> bool:
    if not text: return False
    text_lower = text.lower()
    for word in BANNED_WORDS:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, text_lower):
            return True
    return False

def contains_link(message) -> bool:
    entities = (message.entities or []) + (message.caption_entities or [])
    return any(e.type in ('url', 'text_link') for e in entities)

def create_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    raw_username = job_info.get('username')
    display_username = escape_markdown(f"@{raw_username}") if raw_username else "Not available"
    safe_name = escape_markdown(str(job_info['user_name']))
    safe_uid = escape_markdown(str(job_info['user_id']))
    
    log_message = (
        f"*New {content_type} Confession Log*\n\n"
        f"*User ID:* `{safe_uid}`\n"
        f"*Name:* {safe_name}\n"
        f"*Username:* {display_username}\n\n"
    )
    content_to_log = text_content or job_info.get('caption')
    if content_to_log:
        log_message += f"*Content:*\n{escape_markdown(content_to_log)}"
    return log_message

def create_mod_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    safe_uid = escape_markdown(str(job_info['user_id']))
    log_message = (
        f"*New {content_type} Confession Log (Moderator View)*\n\n"
        f"*User ID:* `{safe_uid}`\n\n"
    )
    content_to_log = text_content or job_info.get('caption')
    if content_to_log:
        log_message += f"*Content:*\n{escape_markdown(content_to_log)}"
    return log_message

# --- Job Queue Functions ---
def post_text(context):
    job_info = context.job.context
    try:
        context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'], timeout=20)
        log_msg = create_log_message(job_info, "Text", text_content=job_info['text'])
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_msg, parse_mode='Markdown', timeout=20)
        mod_log_msg = create_mod_log_message(job_info, "Text", text_content=job_info['text'])
        context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=mod_log_msg, parse_mode='Markdown', timeout=20)
        log_to_gsheet(job_info, text_content=job_info['text'])
    except Exception as e:
        print(f"Post Error: {e}")

def post_photo(context):
    job_info = context.job.context
    try:
        context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'], timeout=30)
        context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        log_msg = create_log_message(job_info, "Photo")
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_msg, parse_mode='Markdown', timeout=30)
        context.bot.send_photo(chat_id=MOD_LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        mod_log_msg = create_mod_log_message(job_info, "Photo")
        context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=mod_log_msg, parse_mode='Markdown', timeout=30)
        log_to_gsheet(job_info, text_content=job_info['caption'], photo_id=job_info['photo'])
    except Exception as e:
        print(f"Post Error: {e}")

# --- Handlers ---
def _schedule_post(update, context, post_type: str):
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    save_user(user.id)
    is_privileged = is_owner_or_mod(user.id)
    
    if is_user_restricted(user.id, update):
        return

    if post_type == 'photo':
        if not PHOTOS_ENABLED and not is_privileged:
            update.message.reply_text("❌ Photo confessions are currently disabled.")
            return
        
        if not is_privileged:
            now = datetime.datetime.now()
            last_photo = user_photo_cooldowns.get(user.id)
            if last_photo and (now - last_photo).total_seconds() < PHOTO_COOLDOWN:
                rem = PHOTO_COOLDOWN - (now - last_photo).total_seconds()
                hours_left = int(rem / 3600)
                minutes_left = int((rem % 3600) / 60)
                update.message.reply_text(f"⏳ Photos are limited to once every {int(PHOTO_COOLDOWN/3600)}h. Wait {hours_left}h {minutes_left}m.")
                return
            user_photo_cooldowns[user.id] = now

    text_to_check = update.message.text if post_type == 'text' else (update.message.caption or "")
    
    if check_for_banned_words(text_to_check) and not is_privileged:
        update.message.reply_text("❌ Your message contains words that are not allowed.")
        return

    if contains_link(update.message):
        if not LINKS_ENABLED and not is_privileged:
            update.message.reply_text("❌ Link sharing is currently disabled.")
            return
        
        if not is_privileged:
            now = datetime.datetime.now()
            last_link = user_link_cooldowns.get(user.id)
            if last_link and (now - last_link).total_seconds() < LINK_COOLDOWN:
                rem = LINK_COOLDOWN - (now - last_link).total_seconds()
                hours_left = int(rem / 3600)
                minutes_left = int((rem % 3600) / 60)
                update.message.reply_text(f"⏳ Links are limited to once every {int(LINK_COOLDOWN/3600)}h. Wait {hours_left}h {minutes_left}m.")
                return
            user_link_cooldowns[user.id] = now

    base_delay = 0
    if not is_bot_active() and not is_privileged:
        base_delay = get_seconds_until_active()
        t_start = format_time(END_HOUR) # Sleep starts at END_HOUR
        t_end = format_time(START_HOUR) # Wakes up at START_HOUR
        update.message.reply_text(f"🌙 Bot is currently in sleep mode ({t_start} - {t_end}). Your confession is queued for {t_end}.")

    now_tz = datetime.datetime.now(TIMEZONE)
    
    if is_privileged:
        final_delay = 0 
    else:
        current_queue_time = user_queues.get(user.id, now_tz)
        if current_queue_time < now_tz: current_queue_time = now_tz
        final_delay = (current_queue_time - now_tz).total_seconds() + base_delay
    
    job_context = {
        'chat_id': CHANNEL_ID, 
        'user_id': user.id, 
        'user_name': user.first_name, 
        'username': user.username
    }
    
    if post_type == 'text':
        job_context['text'] = text_to_check
        context.job_queue.run_once(post_text, final_delay, context=job_context)
    else:
        job_context['photo'] = update.message.photo[-1].file_id
        job_context['caption'] = text_to_check
        context.job_queue.run_once(post_photo, final_delay, context=job_context)

    if not is_privileged:
        user_queues[user.id] = now_tz + datetime.timedelta(seconds=final_delay + POST_DELAY)
    
    if base_delay == 0:
        if final_delay < 1:
            update.message.reply_text("✅ Confession sent anonymously!")
        else:
            update.message.reply_text(f"🕒 Queued. Will be posted in {int(final_delay)} seconds.")

def handle_confession(u, c): _schedule_post(u, c, 'text')
def handle_photo(u, c): _schedule_post(u, c, 'photo')

def handle_delete(update, context):
    if not update.message or not update.message.from_user: return
    user = update.message.from_user
    
    if is_user_restricted(user.id, update): return
    if not update.message.forward_from_chat: return

    target_chat = str(update.message.forward_from_chat.id)
    if target_chat == str(CHANNEL_ID) or f"@{CHANNEL_ID.lstrip('@')}" == target_chat:
        
        is_privileged = is_owner_or_mod(user.id)
        now = datetime.datetime.now()
        
        if not is_privileged:
            last_del = user_delete_cooldowns.get(user.id)
            if last_del and (now - last_del).total_seconds() < DELETE_COOLDOWN:
                update.message.reply_text(f"⏳ Please wait {int(DELETE_COOLDOWN - (now - last_del).total_seconds())}s before deleting again.")
                return

        try:
            msg_id = update.message.forward_from_message_id
            context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            
            if not is_privileged:
                user_delete_cooldowns[user.id] = now
            
            update.message.reply_text("🗑 Message successfully deleted from channel.")
            
            content = update.message.text or update.message.caption or "[Media with no caption]"
            raw_username = user.username
            display_username = f"@{escape_markdown(raw_username)}" if raw_username else "Not available"
            safe_user = escape_markdown(str(user.first_name))
            safe_uid = escape_markdown(str(user.id))
            safe_content = escape_markdown(content)
            
            owner_log_txt = (
                f"🗑 *DELETION LOG*\n"
                f"*By:* {safe_user} (`{safe_uid}`)\n"
                f"*Username:* {display_username}\n"
                f"*Msg ID:* `{msg_id}`\n"
                f"*Original Content:*\n{safe_content}"
            )
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=owner_log_txt, parse_mode='Markdown')

            mod_log_txt = (
                f"🗑 *DELETION LOG (Moderator View)*\n"
                f"*By User ID:* `{safe_uid}`\n"
                f"*Msg ID:* `{msg_id}`\n"
                f"*Original Content:*\n{safe_content}"
            )
            context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=mod_log_txt, parse_mode='Markdown')
            
        except Exception as e: 
            update.message.reply_text(f"❌ Could not delete: {e}")

# --- Admin & Mod Commands ---
def add_mod(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        MODERATORS.add(target)
        with open("moderators.txt", "w") as f:
            for m in MODERATORS: f.write(f"{m}\n")
        update.message.reply_text(f"👮‍♂️ User `{target}` is now a Moderator.", parse_mode='Markdown')
    except: update.message.reply_text("Usage: /addmod <id>")

def remove_mod(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        MODERATORS.discard(target)
        with open("moderators.txt", "w") as f:
            for m in MODERATORS: f.write(f"{m}\n")
        update.message.reply_text(f"✅ User `{target}` is no longer a Moderator.", parse_mode='Markdown')
    except: update.message.reply_text("Usage: /removemod <id>")

def set_time(update, context):
    """Sets the active hours (Owner Only)"""
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        start_h = int(context.args[0])
        end_h = int(context.args[1])
        if not (0 <= start_h <= 23) or not (0 <= end_h <= 23):
            raise ValueError
            
        global START_HOUR, END_HOUR
        START_HOUR = start_h
        END_HOUR = end_h
        save_time_settings()
        
        t_start = format_time(START_HOUR)
        t_end = format_time(END_HOUR)
        update.message.reply_text(f"✅ Active time updated!\nStart: {t_start}\nEnd/Sleep: {t_end}")
    except: 
        update.message.reply_text("Usage: /settime <start_hour_24h> <end_hour_24h>\nExample for 9PM to 6PM: `/settime 21 18`", parse_mode='Markdown')

def broadcast(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    msg_text = " ".join(context.args)
    if not msg_text:
        update.message.reply_text("❌ Incomplete Command!\nUse: `/broadcast Your message here`", parse_mode='Markdown')
        return

    update.message.reply_text(f"📢 Broadcasting to {len(KNOWN_USERS)} users...")
    sent, failed = 0, 0
    for uid in list(KNOWN_USERS):
        try:
            context.bot.send_message(chat_id=uid, text=msg_text)
            sent += 1
            time.sleep(0.05)
        except: failed += 1
    update.message.reply_text(f"✅ Finished.\nSuccess: {sent}\nFailed: {failed}")

def ban_user(update, context):
    if not update.message or not is_owner_or_mod(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        # Join the rest of the arguments as the reason
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided."
        
        BANNED_USERS[target] = reason
        with open("banned_users.txt", "w") as f:
            for u, r in BANNED_USERS.items(): f.write(f"{u},{r}\n")
            
        update.message.reply_text(f"🚫 User `{target}` banned.\n*Reason:* {reason}", parse_mode='Markdown')
        
        # Log Action
        admin = update.message.from_user
        log_txt = (
            f"⚠️ *MODERATOR ACTION: BAN*\n"
            f"*Admin:* {escape_markdown(admin.first_name)} (`{admin.id}`)\n"
            f"*Target User ID:* `{target}`\n"
            f"*Reason:* {escape_markdown(reason)}"
        )
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='Markdown')
    except: update.message.reply_text("Usage: /ban <id> <reason>")

def unban_user(update, context):
    if not update.message or not is_owner_or_mod(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        if target in BANNED_USERS:
            del BANNED_USERS[target]
            with open("banned_users.txt", "w") as f:
                for u, r in BANNED_USERS.items(): f.write(f"{u},{r}\n")
            update.message.reply_text(f"✅ User `{target}` unbanned.", parse_mode='Markdown')
            
            # Log Action
            admin = update.message.from_user
            log_txt = (
                f"⚠️ *MODERATOR ACTION: UNBAN*\n"
                f"*Admin:* {escape_markdown(admin.first_name)} (`{admin.id}`)\n"
                f"*Target User ID:* `{target}`"
            )
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='Markdown')
        else:
            update.message.reply_text("User is not banned.")
    except: update.message.reply_text("Usage: /unban <id>")

def timeout_user(update, context):
    if not update.message or not is_owner_or_mod(update.message.from_user.id): return
    try:
        target_id = int(context.args[0])
        minutes = int(context.args[1])
        reason = " ".join(context.args[2:]) if len(context.args) > 2 else "No reason provided."
        
        expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        USER_TIMEOUTS[target_id] = {'expiry': expiry_time.timestamp(), 'reason': reason}
        save_timeouts()
        update.message.reply_text(f"⏳ User {target_id} timed out for {minutes}m.\n*Reason:* {reason}", parse_mode='Markdown')
        
        admin = update.message.from_user
        log_txt = (
            f"⚠️ *MODERATOR ACTION: TIMEOUT*\n"
            f"*Admin:* {escape_markdown(admin.first_name)} (`{admin.id}`)\n"
            f"*Target User ID:* `{target_id}`\n"
            f"*Duration:* {minutes} minutes\n"
            f"*Reason:* {escape_markdown(reason)}"
        )
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='Markdown')
    except: update.message.reply_text("Usage: /timeout <id> <minutes> <reason>")

def remove_timeout(update, context):
    if not update.message or not is_owner_or_mod(update.message.from_user.id): return
    try:
        target_id = int(context.args[0])
        if target_id in USER_TIMEOUTS:
            del USER_TIMEOUTS[target_id]
            save_timeouts()
            update.message.reply_text(f"✅ Timeout removed for {target_id}.")
            
            admin = update.message.from_user
            log_txt = (
                f"⚠️ *MODERATOR ACTION: UNTIMEOUT*\n"
                f"*Admin:* {escape_markdown(admin.first_name)} (`{admin.id}`)\n"
                f"*Target User ID:* `{target_id}`"
            )
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='Markdown')
        else:
            update.message.reply_text("User is not timed out.")
    except: update.message.reply_text("Usage: /untimeout <id>")

def add_banned_word(update, context):
    if not update.message or not is_owner_or_mod(update.message.from_user.id): return
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.add(word)
        with open("banned_words.txt", "w") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        update.message.reply_text(f"🚫 Banned: {word}")
    except: update.message.reply_text("Usage: /addban <word>")

def remove_banned_word(update, context):
    if not update.message or not is_owner_or_mod(update.message.from_user.id): return
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.discard(word)
        with open("banned_words.txt", "w") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        update.message.reply_text(f"✅ Unbanned: {word}")
    except: update.message.reply_text("Usage: /removeban <word>")

def clear_queue(update, context):
    if not update.message or not update.message.from_user: return
    if is_user_restricted(update.message.from_user.id, update): return

    if update.message.from_user.id in user_queues:
        del user_queues[update.message.from_user.id]
        update.message.reply_text("Queue cleared.")
    else:
        update.message.reply_text("Queue empty.")

# --- Help Conversation ---
def help_command(update, context):
    if not update.message or not update.message.from_user: return AWAITING_HELP_MESSAGE
    if is_user_restricted(update.message.from_user.id, update): return ConversationHandler.END

    update.message.reply_text("Send your query. It will be forwarded to the owner.")
    return AWAITING_HELP_MESSAGE

def forward_help(update, context):
    context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
    update.message.reply_text("Sent to owner.")
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# --- User & Menu Commands ---

def get_main_menu(user_id):
    """Helper function to generate the correct keyboard based on user role."""
    keyboard = []
    
    if is_owner(user_id):
        role_title = "👑 Owner Panel"
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data='menu_stats'), InlineKeyboardButton("⏰ Edit Active Time", callback_data='menu_active_time')],
            [InlineKeyboardButton("👮‍♂️ Manage Mods", callback_data='menu_manage_mods'), InlineKeyboardButton("🚫 Manage Bans", callback_data='menu_manage_bans')],
            [InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts'), InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words')],
            [InlineKeyboardButton("🔗 Toggle Links", callback_data='menu_toggle_links'), InlineKeyboardButton("📸 Toggle Photos", callback_data='menu_toggle_photos')],
            [InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide'), InlineKeyboardButton("🗑️ Clear Queue", callback_data='menu_clear')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    elif user_id in MODERATORS:
        role_title = "👮‍♂️ Moderator Panel"
        keyboard = [
            [InlineKeyboardButton("🚫 Manage Bans", callback_data='menu_manage_bans'), InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts')],
            [InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words')],
            [InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide'), InlineKeyboardButton("🗑️ Clear Queue", callback_data='menu_clear')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    else:
        role_title = "User"
        keyboard = [
            [InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide'), InlineKeyboardButton("🗑️ Clear Queue", callback_data='menu_clear')],
            [InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
        
    return role_title, InlineKeyboardMarkup(keyboard)

def start(update, context):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    if is_user_restricted(user_id, update): return

    save_user(user_id)
    
    role_title, reply_markup = get_main_menu(user_id)
    greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
    
    update.message.reply_text(
        f"{greeting}Send any text or photo to post it anonymously to the channel.\n\n"
        "Click a button below for more options:",
        reply_markup=reply_markup
    )

def menu_button_handler(update, context):
    global LINKS_ENABLED, PHOTOS_ENABLED 
    
    query = update.callback_query
    query.answer() 
    user_id = query.from_user.id

    # --- Common / Return Menu ---
    if query.data == 'menu_back':
        role_title, reply_markup = get_main_menu(user_id)
        greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
        query.edit_message_text(
            f"{greeting}Send any text or photo to post it anonymously to the channel.\n\n"
            "Click a button below for more options:",
            reply_markup=reply_markup
        )

    # --- Standard User Features ---
    elif query.data == 'menu_guide':
        status_links = "✅ Enabled" if LINKS_ENABLED else "❌ Disabled"
        status_photos = "✅ Enabled" if PHOTOS_ENABLED else "❌ Disabled"
        active_status = "✅ Active" if is_bot_active() else "🌙 Resting (Queueing enabled)"
        
        t_start = format_time(START_HOUR)
        t_end = format_time(END_HOUR)
        
        txt = f"""
*Confession Bot Guide*
@TapahConfessions
- Posts are anonymous.
- To delete your post: Forward it from the channel back to this bot.
- Post Cooldown: {POST_DELAY}s between posts.
- Delete Cooldown: {DELETE_COOLDOWN}s between deletions.
- Link Cooldown: {int(LINK_COOLDOWN/3600)} hours between link posts.
- Photo Cooldown: {int(PHOTO_COOLDOWN/3600)} hours between photo posts.
- No banned words allowed.

*Active Hours:*
- {t_start} to {t_end} (GMT+8)
- Current Status: {active_status}

*Permissions:*
- Links: {status_links}
- Photos: {status_photos}
        """
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=markup)

    elif query.data == 'menu_clear':
        if user_id in user_queues:
            del user_queues[user_id]
            query.edit_message_text(text="✅ Your queue has been cleared.")
        else:
            query.edit_message_text(text="⚠️ Your queue is already empty.")

    elif query.data == 'menu_close':
        query.edit_message_text(text="👋 Menu closed. Send a message or photo to confess.")

    # --- Owner & Moderator Submenus ---
    elif query.data == 'menu_stats':
        if not is_owner(user_id): return
        uptime = datetime.datetime.now() - BOT_START_TIME
        uptime_str = str(uptime).split('.')[0] 
        msg = (
            f"📊 *Bot Statistics*\n\n"
            f"👥 *Total Users:* `{len(KNOWN_USERS)}`\n"
            f"🚫 *Banned Users:* `{len(BANNED_USERS)}`\n"
            f"👮‍♂️ *Moderators:* `{len(MODERATORS)}`\n"
            f"⏳ *Uptime:* `{uptime_str}`\n\n"
            f"*Feature Status:*\n"
            f"🔗 Links: {'✅ Enabled' if LINKS_ENABLED else '❌ Disabled'}\n"
            f"📸 Photos: {'✅ Enabled' if PHOTOS_ENABLED else '❌ Disabled'}\n"
            f"🌙 Active Mode: {'✅ Yes' if is_bot_active() else '❌ No (Sleep/Queue Mode)'}"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=markup)
        
    elif query.data == 'menu_toggle_links':
        if not is_owner(user_id): return
        LINKS_ENABLED = not LINKS_ENABLED
        status = 'ENABLED' if LINKS_ENABLED else 'DISABLED'
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=f"🔗 Link restriction is now {'OFF' if LINKS_ENABLED else 'ON'}.", reply_markup=markup)
        context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 Notice: Link sharing has been {status} by the administrator.")

    elif query.data == 'menu_toggle_photos':
        if not is_owner(user_id): return
        PHOTOS_ENABLED = not PHOTOS_ENABLED
        status = 'ENABLED' if PHOTOS_ENABLED else 'DISABLED'
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=f"📸 Photo posts are now {'ENABLED' if PHOTOS_ENABLED else 'DISABLED'}.", reply_markup=markup)
        context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 Notice: Photo confessions have been {status} by the administrator.")

    # -- Interactive Control Panels --
    elif query.data == 'menu_active_time':
        if not is_owner(user_id): return
        t_start = format_time(START_HOUR)
        t_end = format_time(END_HOUR)
        txt = (
            f"⏰ *Active Time Panel*\n\n"
            f"*Current Start Time:* {t_start}\n"
            f"*Current End (Sleep) Time:* {t_end}\n\n"
            f"*How to change it:*\n"
            f"Type `/settime <start_hour> <end_hour>` using the 24-hour clock.\n\n"
            f"_Example for 9 PM to 6 PM:_\n`/settime 21 18`"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=markup)

    elif query.data == 'menu_manage_mods':
        if not is_owner(user_id): return
        txt = (
            "👮‍♂️ *Moderator Management*\n\n"
            "*To Add a Mod:*\n`/addmod <User_ID>`\n\n"
            "*To Remove a Mod:*\n`/removemod <User_ID>`"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=markup)

    elif query.data == 'menu_manage_bans':
        if not is_owner_or_mod(user_id): return
        txt = (
            "🚫 *Ban Management*\n\n"
            "*To Ban a User:*\n`/ban <User_ID> <Reason>`\n"
            "_Example: /ban 123456789 Spamming the chat_\n\n"
            "*To Unban a User:*\n`/unban <User_ID>`"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=markup)

    elif query.data == 'menu_manage_timeouts':
        if not is_owner_or_mod(user_id): return
        txt = (
            "⏳ *Timeout Management*\n\n"
            "*To Timeout a User:*\n`/timeout <User_ID> <Minutes> <Reason>`\n"
            "_Example: /timeout 123456789 60 Flooding_\n\n"
            "*To Remove Timeout:*\n`/untimeout <User_ID>`"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=markup)

    elif query.data == 'menu_manage_words':
        if not is_owner_or_mod(user_id): return
        msg = ", ".join(sorted(BANNED_WORDS)) if BANNED_WORDS else "None."
        txt = (
            f"🤬 *Banned Words Management*\n\n"
            f"*Current Banned Words:*\n`{msg}`\n\n"
            f"*To Add a Word:*\n`/addban <word>`\n\n"
            f"*To Remove a Word:*\n`/removeban <word>`"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        query.edit_message_text(text=txt, parse_mode='Markdown', reply_markup=markup)


def error_handler(update, context):
    if isinstance(context.error, NetworkError):
        return
    print(f"Update {update} caused error {context.error}")

def main():
    try:
        init_google_sheets()
        request_kwargs = {'read_timeout': 30, 'connect_timeout': 30}
        updater = Updater(TOKEN, use_context=True, request_kwargs=request_kwargs)
        dp = updater.dispatcher
        dp.add_error_handler(error_handler)

        dp.add_handler(ConversationHandler(
            entry_points=[CommandHandler('help', help_command)],
            states={AWAITING_HELP_MESSAGE: [MessageHandler(Filters.all & ~Filters.command, forward_help)]},
            fallbacks=[CommandHandler('cancel', cancel)]
        ))

        dp.add_handler(CommandHandler("start", start))
        
        # Menu Interaction Handler
        dp.add_handler(CallbackQueryHandler(menu_button_handler, pattern='^menu_'))
        
        dp.add_handler(CommandHandler("settime", set_time))
        dp.add_handler(CommandHandler("broadcast", broadcast))
        dp.add_handler(CommandHandler("ban", ban_user))
        dp.add_handler(CommandHandler("unban", unban_user))
        
        dp.add_handler(CommandHandler("addmod", add_mod))
        dp.add_handler(CommandHandler("removemod", remove_mod))
        dp.add_handler(CommandHandler("timeout", timeout_user))
        dp.add_handler(CommandHandler("untimeout", remove_timeout))
        
        dp.add_handler(CommandHandler("addban", add_banned_word))
        dp.add_handler(CommandHandler("removeban", remove_banned_word))
        dp.add_handler(CommandHandler("clearqueue", clear_queue))
        
        dp.add_handler(MessageHandler(Filters.forwarded, handle_delete))
        dp.add_handler(MessageHandler(Filters.photo, handle_photo))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_confession))

        updater.start_polling()
        
        now_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
        try:
            updater.bot.send_message(
                chat_id=OWNER_ID, 
                text=f"✅ Bot is up! Running from Raspberry Pi. Started at {now_str}"
            )
        except Exception as e:
            print(f"Warning: Failed to send startup notification: {e}")

        print("--- Bot is Online and Operating ---")
        updater.idle()
    except Exception as e:
        print(f"❌ Failed to start: {e}")

if __name__ == '__main__':
    main()
