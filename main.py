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

# --- Enable Live Terminal Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Load .env file for local testing
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

START_HOUR = 21  
END_HOUR = 18    

LINKS_ENABLED = True
PHOTOS_ENABLED = True

AUTO_REPLY_ENABLED = True
AUTO_REPLY_TEXT = "Use @TapahConfessionBot to submit your confession\n\nIf you're trying to contact the owner, just leave the message as-is.\n\n-Dev"

# --- Terms and Conditions Text ---
TNC_TEXT = (
    "👋 Hello!\n"
    "Welcome to Tapah Confession Bot.\n\n"
    "Send any text or photos to post your confession anonymously to the channel.\n\n"
    "To delete a confession, kindly forward the post to bot.\n\n"
    "Do read our guide for terms and conditions.\n\n"
    "By clicking below button. You agree to the terms and conditions."
)

user_queues: Dict[int, datetime.datetime] = {}
user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {}
user_photo_cooldowns: Dict[int, datetime.datetime] = {} 

AWAITING_HELP_MESSAGE = 0
action_states: Dict[int, str] = {}

# --- Environment Variable Loading & Validation ---
try:
    TOKEN = os.environ.get('BOT_TOKEN')
    CHANNEL_ID = os.environ.get('CHANNEL_ID')
    OWNER_ID_STR = os.environ.get('OWNER_ID')
    LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')
    MOD_LOG_CHANNEL_ID = os.environ.get('MOD_LOG_CHANNEL_ID') 

    if not all([TOKEN, CHANNEL_ID, OWNER_ID_STR, LOG_CHANNEL_ID, MOD_LOG_CHANNEL_ID]):
        missing = [k for k, v in {
            'BOT_TOKEN': TOKEN, 'CHANNEL_ID': CHANNEL_ID, 'OWNER_ID': OWNER_ID_STR, 
            'LOG_CHANNEL_ID': LOG_CHANNEL_ID, 'MOD_LOG_CHANNEL_ID': MOD_LOG_CHANNEL_ID
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
            with open(filename, "r", encoding="utf-8") as f:
                ids = {int(line.strip()) for line in f if line.strip().isdigit()}
        else:
            open(filename, "a", encoding="utf-8").close()
    except Exception as e:
        print(f"Warning: Could not load {filename}: {e}")
    return ids

KNOWN_USERS = load_ids("users.txt")
MODERATORS = load_ids("moderators.txt") 
AGREED_USERS = load_ids("agreed_users.txt") 

def load_time_settings():
    global START_HOUR, END_HOUR
    try:
        if os.path.exists("active_time.txt"):
            with open("active_time.txt", "r", encoding="utf-8") as f:
                parts = f.read().strip().split(',')
                START_HOUR = int(parts[0])
                END_HOUR = int(parts[1])
    except Exception:
        pass

def save_time_settings():
    with open("active_time.txt", "w", encoding="utf-8") as f:
        f.write(f"{START_HOUR},{END_HOUR}")

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
    except Exception:
        pass

def save_autoreply_settings():
    with open("autoreply_status.txt", "w", encoding="utf-8") as f:
        f.write(str(AUTO_REPLY_ENABLED))
    with open("autoreply_text.txt", "w", encoding="utf-8") as f:
        f.write(AUTO_REPLY_TEXT)

load_autoreply_settings()

BANNED_USERS: Dict[int, str] = {}
try:
    if os.path.exists("banned_users.txt"):
        with open("banned_users.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split(',', 1) 
                uid = int(parts[0])
                reason = parts[1] if len(parts) > 1 else "No reason provided."
                BANNED_USERS[uid] = reason
    else:
        open("banned_users.txt", "a", encoding="utf-8").close()
except Exception:
    pass

USER_TIMEOUTS: Dict[int, Dict[str, Union[float, str]]] = {}
try:
    with open("timeouts.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "," in line:
                parts = line.strip().split(',', 2) 
                uid = int(parts[0])
                timestamp = float(parts[1])
                reason = parts[2] if len(parts) > 2 else "No reason provided."
                if float(timestamp) > datetime.datetime.now().timestamp():
                    USER_TIMEOUTS[int(uid)] = {'expiry': timestamp, 'reason': reason}
except FileNotFoundError:
    open("timeouts.txt", "a", encoding="utf-8").close()

BANNED_WORDS: Set[str] = set()
try:
    if os.path.exists("banned_words.txt"):
        with open("banned_words.txt", "r", encoding="utf-8") as f:
            BANNED_WORDS = {line.strip().lower() for line in f if line.strip()}
    else:
        open("banned_words.txt", "a", encoding="utf-8").close()
except Exception:
    pass

# --- Helper Functions ---
def is_owner_or_mod(uid): return uid == OWNER_ID or uid in MODERATORS
def is_owner(uid): return uid == OWNER_ID

def save_timeouts():
    with open("timeouts.txt", "w", encoding="utf-8") as f:
        for uid, data in USER_TIMEOUTS.items():
            if data['expiry'] > datetime.datetime.now().timestamp():
                f.write(f"{uid},{data['expiry']},{data['reason']}\n")

def save_agreed_user(uid):
    if uid not in AGREED_USERS:
        AGREED_USERS.add(uid)
        with open("agreed_users.txt", "a", encoding="utf-8") as f:
            f.write(f"{uid}\n")

async def is_user_restricted(user_id, update: Update):
    if is_owner_or_mod(user_id): return False 
        
    if user_id in BANNED_USERS:
        await update.message.reply_text(f"🚫 You are permanently banned.\n<b>Reason:</b> {html.escape(BANNED_USERS[user_id])}", parse_mode='HTML')
        return True

    if user_id in USER_TIMEOUTS:
        expiry = USER_TIMEOUTS[user_id]['expiry']
        reason = USER_TIMEOUTS[user_id]['reason']
        remaining = expiry - datetime.datetime.now().timestamp()
        if remaining > 0:
            minutes_left = int(remaining / 60) + 1
            await update.message.reply_text(f"⏳ You are in timeout. You cannot use the bot for another {minutes_left} minutes.\n<b>Reason:</b> {html.escape(reason)}", parse_mode='HTML')
            return True
        else:
            del USER_TIMEOUTS[user_id]
            save_timeouts()
            
    return False

def format_time(hour_24):
    am_pm = "AM" if hour_24 < 12 else "PM"
    h = hour_24 if hour_24 <= 12 else hour_24 - 12
    if h == 0: h = 12
    return f"{h:02d}:00 {am_pm}"

def is_bot_active():
    now = datetime.datetime.now(TIMEZONE)
    current_hour = now.hour
    if START_HOUR <= current_hour or current_hour < END_HOUR: return True
    return False

def get_seconds_until_active():
    now = datetime.datetime.now(TIMEZONE)
    target = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    if now.hour >= START_HOUR: target += datetime.timedelta(days=1)
    return (target - now).total_seconds()

def save_user(uid):
    if uid not in KNOWN_USERS:
        KNOWN_USERS.add(uid)
        with open("users.txt", "a", encoding="utf-8") as f:
            f.write(f"{uid}\n")

def check_for_banned_words(text: str) -> bool:
    if not text: return False
    text_lower = text.lower()
    for word in BANNED_WORDS:
        # If the banned word contains only letters/numbers, use strict word boundaries
        if re.match(r'^\w+$', word):
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, text_lower): return True
        else:
            # If the banned word has special characters (like a URL), do a direct literal match
            if word in text_lower: return True
    return False

def contains_link(message) -> bool:
    entities = (message.entities or []) + (message.caption_entities or [])
    return any(e.type in ('url', 'text_link') for e in entities)

def create_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    raw_username = job_info.get('username')
    display_username = f"@{html.escape(raw_username)}" if raw_username else "Not available"
    safe_name = html.escape(str(job_info['user_name']))
    safe_uid = html.escape(str(job_info['user_id']))
    
    log_message = (
        f"<b>New {content_type} Confession Log</b>\n\n"
        f"<b>User ID:</b> <code>{safe_uid}</code>\n"
        f"<b>Name:</b> {safe_name}\n"
        f"<b>Username:</b> {display_username}\n\n"
    )
    content_to_log = text_content or job_info.get('caption')
    if content_to_log: 
        log_message += f"<b>Content:</b>\n{html.escape(content_to_log)}"
    return log_message

def create_mod_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    safe_uid = html.escape(str(job_info['user_id']))
    log_message = (
        f"<b>New {content_type} Confession Log (Moderator View)</b>\n\n"
        f"<b>User ID:</b> <code>{safe_uid}</code>\n\n"
    )
    content_to_log = text_content or job_info.get('caption')
    if content_to_log: 
        log_message += f"<b>Content:</b>\n{html.escape(content_to_log)}"
    return log_message

def get_tnc_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Read Guide", callback_data='tc_guide')],
        [InlineKeyboardButton("✅ I Agree", callback_data='tc_agree')]
    ])

# --- Job Queue Functions ---
async def post_text(context: ContextTypes.DEFAULT_TYPE):
    job_info = context.job.data
    try:
        await context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'], read_timeout=20)
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=create_log_message(job_info, "Text", job_info['text']), parse_mode='HTML', read_timeout=20)
        await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=create_mod_log_message(job_info, "Text", job_info['text']), parse_mode='HTML', read_timeout=20)
    except Exception as e: print(f"Post Error: {e}")

async def post_photo(context: ContextTypes.DEFAULT_TYPE):
    job_info = context.job.data
    try:
        await context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'], read_timeout=30)
        await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=create_log_message(job_info, "Photo"), parse_mode='HTML', read_timeout=30)
        await context.bot.send_photo(chat_id=MOD_LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
        await context.bot.send_message(chat_id=MOD_LOG_CHANNEL_ID, text=create_mod_log_message(job_info, "Photo"), parse_mode='HTML', read_timeout=30)
    except Exception as e: print(f"Post Error: {e}")

# --- Auto Reply for Groups/Channel DMs ---
async def group_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not AUTO_REPLY_ENABLED: return
    msg = update.message
    if not msg or not msg.from_user: return
    
    if str(msg.from_user.id) == str(OWNER_ID): return
    
    raw_msg = msg.to_dict()
    is_channel_dm = raw_msg.get('chat', {}).get('is_direct_messages', False)
    
    if is_channel_dm:
        try:
            await msg.reply_text(AUTO_REPLY_TEXT)
        except Exception as e:
            print(f"❌ Failed to auto-reply to Channel DM: {e}")

# --- Handlers ---
async def _schedule_post(update: Update, context: ContextTypes.DEFAULT_TYPE, post_type: str):
    if not update.message or not update.message.from_user: return

    user = update.message.from_user
    user_id = user.id
    save_user(user_id)
    
    # --- T&C Gatekeeper Check ---
    if user_id not in AGREED_USERS and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    # ----------------------------

    is_privileged = is_owner_or_mod(user_id)
    if await is_user_restricted(user_id, update): return

    # --- DELETE ISOLATION TIMEOUT ---
    text_to_check = update.message.text if post_type == 'text' else (update.message.caption or "")
    text_stripped = text_to_check.strip()
    
    if post_type == 'text' and text_stripped.lower() == 'delete':
        if not is_privileged:
            expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=1)
            USER_TIMEOUTS[user_id] = {'expiry': expiry_time.timestamp(), 'reason': "Invalid deletion attempt. Do not type 'delete'."}
            save_timeouts()
            
            status_links = "✅ Enabled" if LINKS_ENABLED else "❌ Disabled"
            status_photos = "✅ Enabled" if PHOTOS_ENABLED else "❌ Disabled"
            active_status = "✅ Active" if is_bot_active() else "🌙 Resting (Queueing enabled)"
            
            guide_txt = f"""
<b>Confession Bot Guide</b>
@TapahConfessions
- Posts are anonymous.
- To delete your post: <b>Forward it from the channel back to this bot. Do NOT just type 'delete'. Failure to do so will result in timeout.</b>
- Post Cooldown: {POST_DELAY}s between posts.
- Delete Cooldown: {DELETE_COOLDOWN}s between deletions.
- Link Cooldown: {int(LINK_COOLDOWN/3600)} hours between link posts.
- Photo Cooldown: {int(PHOTO_COOLDOWN/3600)} hours between photo posts.
- No banned words allowed.

<b>Active Hours:</b>
- {format_time(START_HOUR)} to {format_time(END_HOUR)} (GMT+8)
- Current Status: {active_status}

<b>Permissions:</b>
- Links: {status_links}
- Photos: {status_photos}
"""
            await update.message.reply_text(f"⚠️ <b>Timeout Applied (1 Minute)</b>\n\nYou typed 'delete'. To delete a confession, you must forward the actual message from the channel here.\n\n{guide_txt}", parse_mode='HTML')
            return
        else:
            await update.message.reply_text("To delete a post, you need to forward the message from the channel. Just typing 'delete' does not work.")
            return
    # --------------------------------

    if post_type == 'photo':
        if not PHOTOS_ENABLED and not is_privileged:
            await update.message.reply_text("❌ Photo confessions are currently disabled.")
            return
        if not is_privileged:
            now = datetime.datetime.now()
            last_photo = user_photo_cooldowns.get(user_id)
            if last_photo and (now - last_photo).total_seconds() < PHOTO_COOLDOWN:
                rem = PHOTO_COOLDOWN - (now - last_photo).total_seconds()
                hours_left = int(rem / 3600)
                minutes_left = int((rem % 3600) / 60)
                await update.message.reply_text(f"⏳ Photos limited to once every {int(PHOTO_COOLDOWN/3600)}h. Wait {hours_left}h {minutes_left}m.")
                return
            user_photo_cooldowns[user_id] = now

    if check_for_banned_words(text_to_check) and not is_privileged:
        await update.message.reply_text("❌ Your message contains words that are not allowed.")
        return

    if contains_link(update.message):
        if not LINKS_ENABLED and not is_privileged:
            await update.message.reply_text("❌ Link sharing is currently disabled.")
            return
        if not is_privileged:
            now = datetime.datetime.now()
            last_link = user_link_cooldowns.get(user_id)
            if last_link and (now - last_link).total_seconds() < LINK_COOLDOWN:
                rem = LINK_COOLDOWN - (now - last_link).total_seconds()
                hours_left = int(rem / 3600)
                minutes_left = int((rem % 3600) / 60)
                await update.message.reply_text(f"⏳ Links limited to once every {int(LINK_COOLDOWN/3600)}h. Wait {hours_left}h {minutes_left}m.")
                return
            user_link_cooldowns[user_id] = now

    base_delay = 0
    if not is_bot_active() and not is_privileged:
        base_delay = get_seconds_until_active()
        await update.message.reply_text(f"🌙 Bot is currently in sleep mode ({format_time(END_HOUR)} - {format_time(START_HOUR)}). Your confession is queued for {format_time(START_HOUR)}.")

    now_tz = datetime.datetime.now(TIMEZONE)
    if is_privileged:
        final_delay = 0 
    else:
        current_queue_time = user_queues.get(user_id, now_tz)
        if current_queue_time < now_tz: current_queue_time = now_tz
        final_delay = (current_queue_time - now_tz).total_seconds() + base_delay
    
    job_context = {'chat_id': CHANNEL_ID, 'user_id': user.id, 'user_name': user.first_name, 'username': user.username}
    
    if post_type == 'text':
        job_context['text'] = text_to_check
        context.job_queue.run_once(post_text, final_delay, data=job_context)
    else:
        job_context['photo'] = update.message.photo[-1].file_id
        job_context['caption'] = text_to_check
        context.job_queue.run_once(post_photo, final_delay, data=job_context)

    if not is_privileged:
        user_queues[user.id] = now_tz + datetime.timedelta(seconds=final_delay + POST_DELAY)
    
    if base_delay == 0:
        if final_delay < 1: await update.message.reply_text("✅ Confession sent anonymously!")
        else: await update.message.reply_text(f"🕒 Queued. Will be posted in {int(final_delay)} seconds.")

    # --- RESTORED: AUTO REPLY FOR 1-ON-1 PRIVATE DMs ---
    if AUTO_REPLY_ENABLED and not is_privileged:
        try:
            await update.message.reply_text(AUTO_REPLY_TEXT)
        except Exception as e:
            print(f"❌ Auto-reply error in Private DM: {e}")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await _schedule_post(update, context, 'text')
    
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    await _schedule_post(update, context, 'photo')

# --- Interactive Input Wrappers ---
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    
    # --- T&C Gatekeeper Check ---
    if user_id not in AGREED_USERS and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    # ----------------------------

    if user_id in action_states:
        state = action_states[user_id]
        context.args = update.message.text.split()
        
        if state == 'trig_ban': await ban_user(update, context)
        elif state == 'trig_unban': await unban_user(update, context)
        elif state == 'trig_timeout': await timeout_user(update, context)
        elif state == 'trig_rmtimeout': await remove_timeout(update, context)
        elif state == 'trig_addmod': await add_mod(update, context)
        elif state == 'trig_rmmod': await remove_mod(update, context)
        elif state == 'trig_addword': await add_banned_word(update, context)
        elif state == 'trig_rmword': await remove_banned_word(update, context)
        elif state == 'trig_settime': await set_time(update, context)
        elif state == 'trig_setautoreply': 
            global AUTO_REPLY_TEXT
            AUTO_REPLY_TEXT = update.message.text
            save_autoreply_settings()
            await update.message.reply_text("✅ Auto-reply message updated successfully!")
        
        del action_states[user_id]
        return
    await handle_confession(update, context)

async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    
    # --- T&C Gatekeeper Check ---
    if user_id not in AGREED_USERS and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    # ----------------------------

    if user_id in action_states:
        await update.message.reply_text("❌ Action cancelled. I was expecting text for the command.")
        del action_states[user_id]
        return
    await handle_photo(update, context)

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user = update.message.from_user
    user_id = user.id
    
    # --- T&C Gatekeeper Check ---
    if user_id not in AGREED_USERS and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    # ----------------------------

    if await is_user_restricted(user.id, update): return
    if not update.message.forward_from_chat: return

    target_chat = str(update.message.forward_from_chat.id)
    if target_chat == str(CHANNEL_ID) or f"@{CHANNEL_ID.lstrip('@')}" == target_chat:
        is_privileged = is_owner_or_mod(user_id)
        now = datetime.datetime.now()
        
        if not is_privileged:
            last_del = user_delete_cooldowns.get(user_id)
            if last_del and (now - last_del).total_seconds() < DELETE_COOLDOWN:
                await update.message.reply_text(f"⏳ Please wait {int(DELETE_COOLDOWN - (now - last_del).total_seconds())}s before deleting again.")
                return

        try:
            msg_id = update.message.forward_from_message_id
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            
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

# --- Admin & Mod Commands ---
async def add_mod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(context.args[0])
        MODERATORS.add(target)
        with open("moderators.txt", "w", encoding="utf-8") as f:
            for m in MODERATORS: f.write(f"{m}\n")
        await update.message.reply_text(f"👮‍♂️ User <code>{target}</code> is now a Moderator.", parse_mode='HTML')
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def remove_mod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(context.args[0])
        MODERATORS.discard(target)
        with open("moderators.txt", "w", encoding="utf-8") as f:
            for m in MODERATORS: f.write(f"{m}\n")
        await update.message.reply_text(f"✅ User <code>{target}</code> is no longer a Moderator.", parse_mode='HTML')
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def set_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start_h = int(context.args[0])
        end_h = int(context.args[1])
        if not (0 <= start_h <= 23) or not (0 <= end_h <= 23): raise ValueError
        global START_HOUR, END_HOUR
        START_HOUR, END_HOUR = start_h, end_h
        save_time_settings()
        await update.message.reply_text(f"✅ Active time updated!\nStart: {format_time(START_HOUR)}\nEnd/Sleep: {format_time(END_HOUR)}")
    except: await update.message.reply_text("❌ Error. Ensure you use the 24-hour format.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not is_owner(update.message.from_user.id): return
    msg_text = " ".join(context.args)
    if not msg_text:
        await update.message.reply_text("❌ Incomplete Command!\nUse: <code>/broadcast Your message here</code>", parse_mode='HTML')
        return
    await update.message.reply_text(f"📢 Broadcasting to {len(KNOWN_USERS)} users...")
    sent, failed = 0, 0
    for uid in list(KNOWN_USERS):
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            sent += 1
            await asyncio.sleep(0.05)
        except: failed += 1
    await update.message.reply_text(f"✅ Finished.\nSuccess: {sent}\nFailed: {failed}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided."
        BANNED_USERS[target] = reason
        with open("banned_users.txt", "w", encoding="utf-8") as f:
            for u, r in BANNED_USERS.items(): f.write(f"{u},{r}\n")
        await update.message.reply_text(f"🚫 User `{target}` banned.\n<b>Reason:</b> {html.escape(reason)}", parse_mode='HTML')
        admin = update.message.from_user
        log_txt = f"⚠️ <b>MODERATOR ACTION: BAN</b>\n<b>Admin:</b> {html.escape(admin.first_name)} (<code>{admin.id}</code>)\n<b>Target:</b> <code>{target}</code>\n<b>Reason:</b> {html.escape(reason)}"
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='HTML')
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = int(context.args[0])
        if target in BANNED_USERS:
            del BANNED_USERS[target]
            with open("banned_users.txt", "w", encoding="utf-8") as f:
                for u, r in BANNED_USERS.items(): f.write(f"{u},{r}\n")
            await update.message.reply_text(f"✅ User <code>{target}</code> unbanned.", parse_mode='HTML')
            admin = update.message.from_user
            log_txt = f"⚠️ <b>MODERATOR ACTION: UNBAN</b>\n<b>Admin:</b> {html.escape(admin.first_name)} (<code>{admin.id}</code>)\n<b>Target:</b> <code>{target}</code>"
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='HTML')
        else: await update.message.reply_text("❌ User is not currently banned.")
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def timeout_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(context.args[0])
        minutes = int(context.args[1])
        reason = " ".join(context.args[2:]) if len(context.args) > 2 else "No reason provided."
        expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        USER_TIMEOUTS[target_id] = {'expiry': expiry_time.timestamp(), 'reason': reason}
        save_timeouts()
        await update.message.reply_text(f"⏳ User {target_id} timed out for {minutes}m.\n<b>Reason:</b> {html.escape(reason)}", parse_mode='HTML')
        admin = update.message.from_user
        log_txt = f"⚠️ <b>MODERATOR ACTION: TIMEOUT</b>\n<b>Admin:</b> {html.escape(admin.first_name)} (<code>{admin.id}</code>)\n<b>Target:</b> <code>{target_id}</code>\n<b>Duration:</b> {minutes}m\n<b>Reason:</b> {html.escape(reason)}"
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='HTML')
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def remove_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(context.args[0])
        if target_id in USER_TIMEOUTS:
            del USER_TIMEOUTS[target_id]
            save_timeouts()
            await update.message.reply_text(f"✅ Timeout removed for {target_id}.")
            admin = update.message.from_user
            log_txt = f"⚠️ <b>MODERATOR ACTION: UNTIMEOUT</b>\n<b>Admin:</b> {html.escape(admin.first_name)} (<code>{admin.id}</code>)\n<b>Target:</b> <code>{target_id}</code>"
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='HTML')
        else: await update.message.reply_text("❌ User is not timed out.")
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def add_banned_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.add(word)
        with open("banned_words.txt", "w", encoding="utf-8") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        await update.message.reply_text(f"🚫 Banned word added: {word}")
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def remove_banned_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.discard(word)
        with open("banned_words.txt", "w", encoding="utf-8") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        await update.message.reply_text(f"✅ Banned word removed: {word}")
    except: await update.message.reply_text("❌ Error. Incorrect format used.")

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    if await is_user_restricted(update.message.from_user.id, update): return
    if update.message.from_user.id in user_queues:
        del user_queues[update.message.from_user.id]
        await update.message.reply_text("Queue cleared.")
    else: await update.message.reply_text("Queue empty.")

# --- Help Conversation & Global Cancel ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return AWAITING_HELP_MESSAGE
    user_id = update.message.from_user.id
    
    # --- T&C Gatekeeper Check ---
    if user_id not in AGREED_USERS and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return ConversationHandler.END
    # ----------------------------

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

# --- User & Menu Commands ---
def get_main_menu(user_id):
    keyboard = []
    if is_owner(user_id):
        role_title = "👑 Owner Panel"
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data='menu_stats'), InlineKeyboardButton("⏰ Active Time", callback_data='menu_active_time')],
            [InlineKeyboardButton("🤖 Auto-Reply", callback_data='menu_autoreply'), InlineKeyboardButton("📜 T&C Stats", callback_data='menu_tnc_stats')],
            [InlineKeyboardButton("🤬 Banned Words", callback_data='menu_manage_words'), InlineKeyboardButton("👮‍♂️ Manage Mods", callback_data='menu_manage_mods')],
            [InlineKeyboardButton("🚫 Manage Bans", callback_data='menu_manage_bans'), InlineKeyboardButton("⏳ Manage Timeouts", callback_data='menu_manage_timeouts')],
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
            [InlineKeyboardButton("📖 Read Guide", callback_data='menu_guide'), InlineKeyboardButton("🤬 View Banned Words", callback_data='menu_view_words')],
            [InlineKeyboardButton("🗑️ Clear Queue", callback_data='menu_clear'), InlineKeyboardButton("❌ Close Menu", callback_data='menu_close')]
        ]
    return role_title, InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user: return
    user_id = update.message.from_user.id
    
    # --- T&C Gatekeeper Check ---
    if user_id not in AGREED_USERS and not is_owner(user_id):
        await update.message.reply_text(TNC_TEXT, reply_markup=get_tnc_keyboard())
        return
    # ----------------------------

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

    # --- T&C Agreement Handler ---
    if query.data == 'tc_agree':
        save_agreed_user(user_id)
        role_title, reply_markup = get_main_menu(user_id)
        greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
        await query.edit_message_text(
            f"✅ Thank you for agreeing to the Terms and Conditions!\n\n{greeting}Send any text or photo to post it anonymously to the channel.\n\nClick a button below for more options:",
            reply_markup=reply_markup
        )
        return

    # --- Guide preview before T&C Acceptance ---
    elif query.data == 'tc_guide':
        status_links = "✅ Enabled" if LINKS_ENABLED else "❌ Disabled"
        status_photos = "✅ Enabled" if PHOTOS_ENABLED else "❌ Disabled"
        active_status = "✅ Active" if is_bot_active() else "🌙 Resting (Queueing enabled)"
        
        txt = f"""
<b>Confession Bot Guide</b>
@TapahConfessions
- Posts are anonymous.
- To delete your post: <b>Forward it from the channel back to this bot. Do NOT just type 'delete'. Failure to do so will result in timeout.</b>
- Post Cooldown: {POST_DELAY}s between posts.
- Delete Cooldown: {DELETE_COOLDOWN}s between deletions.
- Link Cooldown: {int(LINK_COOLDOWN/3600)} hours between link posts.
- Photo Cooldown: {int(PHOTO_COOLDOWN/3600)} hours between photo posts.
- No banned words allowed.

<b>Active Hours:</b>
- {format_time(START_HOUR)} to {format_time(END_HOUR)} (GMT+8)
- Current Status: {active_status}

<b>Permissions:</b>
- Links: {status_links}
- Photos: {status_photos}
        """
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back to T&C", callback_data='tc_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)
        return

    # --- Return back to T&C from Guide ---
    elif query.data == 'tc_back':
        await query.edit_message_text(text=TNC_TEXT, reply_markup=get_tnc_keyboard())
        return

    if query.data == 'menu_back':
        if user_id in action_states: del action_states[user_id]
        role_title, reply_markup = get_main_menu(user_id)
        greeting = f"👋 Hello! (Role: {role_title})\n\n" if role_title != "User" else "👋 Hello!\n\n"
        await query.edit_message_text(f"{greeting}Send any text or photo to post it anonymously to the channel.\n\nClick a button below for more options:", reply_markup=reply_markup)

    elif query.data == 'menu_guide':
        status_links = "✅ Enabled" if LINKS_ENABLED else "❌ Disabled"
        status_photos = "✅ Enabled" if PHOTOS_ENABLED else "❌ Disabled"
        active_status = "✅ Active" if is_bot_active() else "🌙 Resting (Queueing enabled)"
        
        txt = f"""
<b>Confession Bot Guide</b>
@TapahConfessions
- Posts are anonymous.
- To delete your post: <b>Forward it from the channel back to this bot. Do NOT just type 'delete'. Failure to do so will result in timeout.</b>
- Post Cooldown: {POST_DELAY}s between posts.
- Delete Cooldown: {DELETE_COOLDOWN}s between deletions.
- Link Cooldown: {int(LINK_COOLDOWN/3600)} hours between link posts.
- Photo Cooldown: {int(PHOTO_COOLDOWN/3600)} hours between photo posts.
- No banned words allowed.

<b>Active Hours:</b>
- {format_time(START_HOUR)} to {format_time(END_HOUR)} (GMT+8)
- Current Status: {active_status}

<b>Permissions:</b>
- Links: {status_links}
- Photos: {status_photos}
        """
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_clear':
        if user_id in user_queues:
            del user_queues[user_id]
            await query.edit_message_text(text="✅ Your queue has been cleared.")
        else: await query.edit_message_text(text="⚠️ Your queue is already empty.")

    elif query.data == 'menu_close':
        if user_id in action_states: del action_states[user_id]
        await query.edit_message_text(text="👋 Menu closed. Send a message or photo to confess.")

    elif query.data == 'menu_stats':
        if not is_owner(user_id): return
        uptime_str = str(datetime.datetime.now() - BOT_START_TIME).split('.')[0] 
        msg = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{len(KNOWN_USERS)}</code>\n"
            f"✅ <b>Agreed Users:</b> <code>{len(AGREED_USERS)}</code>\n"
            f"🚫 <b>Banned Users:</b> <code>{len(BANNED_USERS)}</code>\n"
            f"👮‍♂️ <b>Moderators:</b> <code>{len(MODERATORS)}</code>\n"
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
        total_users = len(KNOWN_USERS)
        agreed_users = len(AGREED_USERS)
        pending_users = total_users - agreed_users
        msg = (
            f"📜 <b>Terms & Conditions Stats</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
            f"✅ <b>Agreed:</b> <code>{agreed_users}</code>\n"
            f"⏳ <b>Pending Agreement:</b> <code>{pending_users}</code>\n\n"
            f"<i>Note: Users in the 'Pending' list cannot send confessions or use the bot until they click 'I Agree'.</i>"
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
        if not is_owner_or_mod(user_id): return
        txt = "🚫 <b>Ban Management</b>\nChoose an action below:"
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
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👁️ View Words", callback_data='menu_view_words')],
            [InlineKeyboardButton("➕ Add Word", callback_data='trig_addword'), InlineKeyboardButton("➖ Remove Word", callback_data='trig_rmword')],
            [InlineKeyboardButton("◀️ Back", callback_data='menu_back')]
        ])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'menu_view_words':
        msg = ", ".join(sorted(BANNED_WORDS)) if BANNED_WORDS else "None."
        txt = f"🤬 <b>Current Banned Words:</b>\n<code>{html.escape(msg)}</code>"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='menu_manage_words' if is_owner_or_mod(user_id) else 'menu_back')]])
        await query.edit_message_text(text=txt, parse_mode='HTML', reply_markup=markup)

    elif query.data.startswith('trig_'):
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
        await query.edit_message_text(text=prompts.get(query.data, "Please provide input. Type /cancel to abort."), parse_mode='HTML')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError): return
    print(f"Update {update} caused error {context.error}")

async def post_init(application: Application):
    now_str = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
    try:
        await application.bot.send_message(chat_id=OWNER_ID, text=f"✅ Bot is up! Running v20+. Started at {now_str}")
    except Exception as e: 
        print(f"Warning: Failed to send startup notification: {e}")

def main():
    # --- PYTHON 3.14 EVENT LOOP FIX ---
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # ----------------------------------

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .read_timeout(30)
        .connect_timeout(30)
        .build()
    )
    
    application.add_error_handler(error_handler)

    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={AWAITING_HELP_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, forward_help)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    ))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel)) 
    application.add_handler(CallbackQueryHandler(menu_button_handler, pattern='^(menu_|trig_|toggle_|tc_)'))
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
    
    # --- THE ROUTING FIX ---
    application.add_handler(MessageHandler(filters.FORWARDED, handle_delete))
    
    # Channel DMs / Groups go to the Auto-Reply
    application.add_handler(MessageHandler((filters.ChatType.SUPERGROUP | filters.ChatType.GROUPS) & ~filters.COMMAND, group_auto_reply))
    
    # 1-on-1 Private DMs go to the Confession Queue
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo_input))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_input))

    print("--- Bot is Online and Operating ---")
    
    application.run_polling()

if __name__ == '__main__':
    main()
