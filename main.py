import os
import sys
import datetime
import time
import re
import logging
from telegram.ext import (
    Updater,
    MessageHandler,
    Filters,
    CommandHandler,
    ConversationHandler,
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
POST_DELAY = 15  # Cooldown between posts for all users, in seconds
DELETE_COOLDOWN = 60  # Cooldown for deleting posts, in seconds
LINK_COOLDOWN = 14400 # 4 Hours cooldown for links
TIMEZONE = pytz.timezone('Asia/Kuala_Lumpur') # GMT+8

# Track when the bot started for Uptime statistics
BOT_START_TIME = datetime.datetime.now()

# Active Hours (24h format)
START_HOUR = 18  # 06:00
END_HOUR = 21    # 02:00 (Next day)

# Feature Toggles
LINKS_ENABLED = True
PHOTOS_ENABLED = True

# In-memory storage for queues
user_queues: Dict[int, datetime.datetime] = {}
user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {}

# States for ConversationHandler
AWAITING_HELP_MESSAGE = 0

# --- Environment Variable Loading & Validation ---
try:
    TOKEN = os.environ.get('BOT_TOKEN')
    CHANNEL_ID = os.environ.get('CHANNEL_ID')
    OWNER_ID_STR = os.environ.get('OWNER_ID')
    LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')
    GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME', 'ConfessionLogs') 

    if not all([TOKEN, CHANNEL_ID, OWNER_ID_STR, LOG_CHANNEL_ID]):
        missing = [k for k, v in {
            'BOT_TOKEN': TOKEN, 
            'CHANNEL_ID': CHANNEL_ID, 
            'OWNER_ID': OWNER_ID_STR, 
            'LOG_CHANNEL_ID': LOG_CHANNEL_ID
        }.items() if not v]
        print(f"❌ CRITICAL ERROR: Missing .env variables: {', '.join(missing)}")
        sys.exit(1)
    
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    print("❌ CRITICAL ERROR: OWNER_ID must be a number in your .env file.")
    sys.exit(1)

# --- Persistence Loading ---

# 1. Banned Users
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

BANNED_USERS = load_ids("banned_users.txt") 

# 2. Timeouts
USER_TIMEOUTS: Dict[int, float] = {}
try:
    with open("timeouts.txt", "r") as f:
        for line in f:
            if "," in line:
                uid, timestamp = line.strip().split(",")
                if float(timestamp) > datetime.datetime.now().timestamp():
                    USER_TIMEOUTS[int(uid)] = float(timestamp)
except FileNotFoundError:
    open("timeouts.txt", "a").close()

# 3. Known Users (For Stats/Broadcast)
KNOWN_USERS = load_ids("users.txt")

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
    """Initializes the connection to Google Sheets."""
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
    """Logs the confession data to Google Sheets."""
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

def save_timeouts():
    """Saves the current active timeouts to file."""
    with open("timeouts.txt", "w") as f:
        for uid, timestamp in USER_TIMEOUTS.items():
            if timestamp > datetime.datetime.now().timestamp():
                f.write(f"{uid},{timestamp}\n")

def is_bot_active():
    """Checks if current time is within 06:00 - 02:00 GMT+8."""
    now = datetime.datetime.now(TIMEZONE)
    current_hour = now.hour
    if START_HOUR <= current_hour or current_hour < END_HOUR:
        return True
    return False

def get_seconds_until_active():
    """Calculates wait time until 06:00 AM."""
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
    """Checks if the given text contains any banned words."""
    if not text: return False
    text_lower = text.lower()
    for word in BANNED_WORDS:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, text_lower):
            return True
    return False

def contains_link(message) -> bool:
    """Checks if the message or caption contains a URL entity."""
    entities = (message.entities or []) + (message.caption_entities or [])
    return any(e.type in ('url', 'text_link') for e in entities)

def create_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    """Creates a crash-proof log message using MarkdownV2 escaping."""
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

# --- Job Queue Functions ---

def post_text(context):
    """Job queue function to post text."""
    job_info = context.job.context
    try:
        # 1. Post to Public Channel
        context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'], timeout=20)
        
        # 2. Post to Log Channel
        log_msg = create_log_message(job_info, "Text", text_content=job_info['text'])
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_msg, parse_mode='Markdown', timeout=20)
        
        # 3. Log to Google Sheet
        log_to_gsheet(job_info, text_content=job_info['text'])
    except Exception as e:
        print(f"Post Error: {e}")

def post_photo(context):
    """Job queue function to post photo."""
    job_info = context.job.context
    try:
        # 1. Post to Public Channel
        context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'], timeout=30)
        
        # 2. Post to Log Channel - Separate photo from metadata
        # Send Photo first (with original caption)
        context.bot.send_photo(
            chat_id=LOG_CHANNEL_ID, 
            photo=job_info['photo'], 
            caption=job_info['caption']
        )
        
        # Send Log Metadata
        log_msg = create_log_message(job_info, "Photo")
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_msg, parse_mode='Markdown', timeout=30)
        
        # 3. Log to Google Sheet
        log_to_gsheet(job_info, text_content=job_info['caption'], photo_id=job_info['photo'])
    except Exception as e:
        print(f"Post Error: {e}")

# --- Handlers ---

def _schedule_post(update, context, post_type: str):
    """Handles logic for checking bans, timeouts, and scheduling."""
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    save_user(user.id)
    
    # 1. Ban Check
    if user.id in BANNED_USERS:
        update.message.reply_text("🚫 You are banned.")
        return 

    # 2. Timeout Check
    if user.id in USER_TIMEOUTS:
        expiry = USER_TIMEOUTS[user.id]
        remaining = expiry - datetime.datetime.now().timestamp()
        if remaining > 0:
            minutes_left = int(remaining / 60)
            update.message.reply_text(f"You are in timeout for breaking rules. You can post again in {minutes_left} minutes.")
            return
        else:
            del USER_TIMEOUTS[user.id]
            save_timeouts()

    # --- Feature Toggle: Photo ---
    if post_type == 'photo' and not PHOTOS_ENABLED:
        update.message.reply_text("❌ Photo confessions are currently disabled.")
        return

    text_to_check = update.message.text if post_type == 'text' else (update.message.caption or "")
    
    # 3. Banned Word Check
    if check_for_banned_words(text_to_check):
        update.message.reply_text("❌ Your message contains words that are not allowed.")
        return

    # 4. Link Check & Toggle
    if contains_link(update.message):
        if not LINKS_ENABLED:
            update.message.reply_text("❌ Link sharing is currently disabled.")
            return
        
        now = datetime.datetime.now()
        last_link = user_link_cooldowns.get(user.id)
        if last_link and (now - last_link).total_seconds() < LINK_COOLDOWN:
            rem = LINK_COOLDOWN - (now - last_link).total_seconds()
            update.message.reply_text(f"⏳ Links are limited to once every 4h. Wait {int(rem/3600)}h {int((rem%3600)/60)}m.")
            return
        user_link_cooldowns[user.id] = now

    # 5. Active Time Check (Queueing)
    base_delay = 0
    if not is_bot_active() and user.id != OWNER_ID:
        base_delay = get_seconds_until_active()
        update.message.reply_text(f"🌙 Bot is currently in sleep mode (02:00-06:00). Your confession is queued for 06:00 AM.")

    # 6. Queue Calculation
    now_tz = datetime.datetime.now(TIMEZONE)
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

    user_queues[user.id] = now_tz + datetime.timedelta(seconds=final_delay + POST_DELAY)
    
    if base_delay == 0:
        if final_delay < 1:
            update.message.reply_text("✅ Confession sent anonymously!")
        else:
            update.message.reply_text(f"🕒 Queued. Will be posted in {int(final_delay)} seconds.")

def handle_confession(u, c): _schedule_post(u, c, 'text')
def handle_photo(u, c): _schedule_post(u, c, 'photo')

def handle_delete(update, context):
    """Handles deletion and logs who deleted what."""
    if not update.message or not update.message.from_user: return
    user = update.message.from_user
    
    if user.id in BANNED_USERS or not update.message.forward_from_chat: return

    target_chat = str(update.message.forward_from_chat.id)
    if target_chat == str(CHANNEL_ID) or f"@{CHANNEL_ID.lstrip('@')}" == target_chat:
        now = datetime.datetime.now()
        last_del = user_delete_cooldowns.get(user.id)
        if last_del and (now - last_del).total_seconds() < DELETE_COOLDOWN:
            update.message.reply_text(f"⏳ Please wait {int(DELETE_COOLDOWN - (now - last_del).total_seconds())}s before deleting again.")
            return

        try:
            msg_id = update.message.forward_from_message_id
            context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            user_delete_cooldowns[user.id] = now
            update.message.reply_text("🗑 Message successfully deleted from channel.")
            
            # --- DELETION LOG ---
            content = update.message.text or update.message.caption or "[Media with no caption]"
            raw_username = user.username
            display_username = f"@{escape_markdown(raw_username)}" if raw_username else "Not available"
            safe_user = escape_markdown(str(user.first_name))
            safe_uid = escape_markdown(str(user.id))
            safe_content = escape_markdown(content)
            
            log_txt = (
                f"🗑 *DELETION LOG*\n"
                f"*By:* {safe_user} (`{safe_uid}`)\n"
                f"*Username:* {display_username}\n"
                f"*Msg ID:* `{msg_id}`\n"
                f"*Original Content:*\n{safe_content}"
            )
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='Markdown')
            
        except Exception as e: 
            update.message.reply_text(f"❌ Could not delete: {e}")

# --- Admin Commands (Full Suite) ---

def is_owner(uid): 
    return uid == OWNER_ID

def stats(update, context):
    """Shows bot statistics (Owner Only)"""
    if not update.message or not is_owner(update.message.from_user.id): return
    
    # Calculate Uptime
    uptime = datetime.datetime.now() - BOT_START_TIME
    uptime_str = str(uptime).split('.')[0] # Format as HH:MM:SS
    
    msg = (
        f"📊 *Bot Statistics*\n\n"
        f"👥 *Total Users:* `{len(KNOWN_USERS)}`\n"
        f"🚫 *Banned Users:* `{len(BANNED_USERS)}`\n"
        f"⏳ *Uptime:* `{uptime_str}`\n\n"
        f"*Feature Status:*\n"
        f"🔗 Links: {'✅ Enabled' if LINKS_ENABLED else '❌ Disabled'}\n"
        f"📸 Photos: {'✅ Enabled' if PHOTOS_ENABLED else '❌ Disabled'}\n"
        f"🌙 Active Mode: {'✅ Yes' if is_bot_active() else '❌ No (Sleep/Queue Mode)'}"
    )
    update.message.reply_text(msg, parse_mode='Markdown')

def toggle_links(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    global LINKS_ENABLED
    LINKS_ENABLED = not LINKS_ENABLED
    status = 'ENABLED' if LINKS_ENABLED else 'DISABLED'
    update.message.reply_text(f"🔗 Link restriction is now {'OFF' if LINKS_ENABLED else 'ON'}.")
    context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 Notice: Link sharing has been {status} by the administrator.")

def toggle_photos(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    global PHOTOS_ENABLED
    PHOTOS_ENABLED = not PHOTOS_ENABLED
    status = 'ENABLED' if PHOTOS_ENABLED else 'DISABLED'
    update.message.reply_text(f"📸 Photo posts are now {'ENABLED' if PHOTOS_ENABLED else 'DISABLED'}.")
    context.bot.send_message(chat_id=CHANNEL_ID, text=f"📢 Notice: Photo confessions have been {status} by the administrator.")

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
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        BANNED_USERS.add(target)
        with open("banned_users.txt", "w") as f:
            for u in BANNED_USERS: f.write(f"{u}\n")
        update.message.reply_text(f"🚫 User `{target}` has been banned.", parse_mode='Markdown')
    except: update.message.reply_text("Usage: /ban <id>")

def unban_user(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        BANNED_USERS.discard(target)
        with open("banned_users.txt", "w") as f:
            for u in BANNED_USERS: f.write(f"{u}\n")
        update.message.reply_text(f"✅ User `{target}` unbanned.", parse_mode='Markdown')
    except: update.message.reply_text("Usage: /unban <id>")

def timeout_user(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        target_id = int(context.args[0])
        minutes = int(context.args[1])
        expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        USER_TIMEOUTS[target_id] = expiry_time.timestamp()
        save_timeouts()
        update.message.reply_text(f"⏳ User {target_id} timed out for {minutes}m.")
    except: update.message.reply_text("Usage: /timeout <id> <minutes>")

def remove_timeout(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        target_id = int(context.args[0])
        if target_id in USER_TIMEOUTS:
            del USER_TIMEOUTS[target_id]
            save_timeouts()
            update.message.reply_text(f"✅ Timeout removed for {target_id}.")
        else:
            update.message.reply_text("User is not timed out.")
    except: update.message.reply_text("Usage: /untimeout <id>")

def add_banned_word(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.add(word)
        with open("banned_words.txt", "w") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        update.message.reply_text(f"🚫 Banned: {word}")
    except: update.message.reply_text("Usage: /addban <word>")

def remove_banned_word(update, context):
    if not update.message or not is_owner(update.message.from_user.id): return
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.discard(word)
        with open("banned_words.txt", "w") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        update.message.reply_text(f"✅ Unbanned: {word}")
    except: update.message.reply_text("Usage: /removeban <word>")

def clear_queue(update, context):
    if update.message.from_user.id in user_queues:
        del user_queues[update.message.from_user.id]
        update.message.reply_text("Queue cleared.")
    else:
        update.message.reply_text("Queue empty.")

def banned_words_list(update, context):
    msg = ", ".join(sorted(BANNED_WORDS)) if BANNED_WORDS else "None."
    update.message.reply_text(f"Banned words: {msg}")

# --- Help Conversation ---
def help_command(update, context):
    update.message.reply_text("Send your query. It will be forwarded to the owner.")
    return AWAITING_HELP_MESSAGE

def forward_help(update, context):
    context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
    update.message.reply_text("Sent to owner.")
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# --- User Commands ---

def start(update, context):
    if not update.message: return
    save_user(update.message.from_user.id)
    update.message.reply_text("👋 Hello! Send any text or photo to post it anonymously to the channel.")

def guide(update, context):
    if not update.message: return
    status_links = "✅ Enabled" if LINKS_ENABLED else "❌ Disabled"
    status_photos = "✅ Enabled" if PHOTOS_ENABLED else "❌ Disabled"
    active_status = "✅ Active" if is_bot_active() else "🌙 Resting (Queueing enabled)"
    
    txt = f"""
*Confession Bot Guide*
@TapahConfessions
- Posts are anonymous.
- To delete your post: Forward it from the channel back to this bot.
- Post Cooldown: {POST_DELAY}s between posts.
- Delete Cooldown: {DELETE_COOLDOWN}s between deletions.
- Link Cooldown: 4 hours between link posts.
- No banned words allowed.

*Operating Hours:*
- 06:00 AM to 02:00 AM (GMT+8)
- Current Status: {active_status}

*Permissions:*
- Links: {status_links}
- Photos: {status_photos}
    """
    update.message.reply_text(txt, parse_mode='Markdown')

def error_handler(update, context):
    """Log the error and inform the user if possible."""
    if isinstance(context.error, NetworkError):
        # Ignore network errors in console to keep logs clean
        return
    print(f"Update {update} caused error {context.error}")

def main():
    try:
        init_google_sheets()
        request_kwargs = {'read_timeout': 30, 'connect_timeout': 30}
        updater = Updater(TOKEN, use_context=True, request_kwargs=request_kwargs)
        dp = updater.dispatcher
        dp.add_error_handler(error_handler)

        # Help Conversation
        dp.add_handler(ConversationHandler(
            entry_points=[CommandHandler('help', help_command)],
            states={AWAITING_HELP_MESSAGE: [MessageHandler(Filters.all & ~Filters.command, forward_help)]},
            fallbacks=[CommandHandler('cancel', cancel)]
        ))

        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("guide", guide))
        
        # Stats & Admin
        dp.add_handler(CommandHandler("stats", stats))
        dp.add_handler(CommandHandler("broadcast", broadcast))
        dp.add_handler(CommandHandler("ban", ban_user))
        dp.add_handler(CommandHandler("unban", unban_user))
        dp.add_handler(CommandHandler("timeout", timeout_user))
        dp.add_handler(CommandHandler("untimeout", remove_timeout))
        dp.add_handler(CommandHandler("addban", add_banned_word))
        dp.add_handler(CommandHandler("removeban", remove_banned_word))
        dp.add_handler(CommandHandler("clearqueue", clear_queue))
        dp.add_handler(CommandHandler("bannedwords", banned_words_list))
        dp.add_handler(CommandHandler("toggle_links", toggle_links))
        dp.add_handler(CommandHandler("toggle_photos", toggle_photos))
        
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
