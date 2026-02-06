import os
import sys
import datetime
import time
import re
from telegram.ext import (
    Updater,
    MessageHandler,
    Filters,
    CommandHandler,
    ConversationHandler,
)
from telegram.error import BadRequest, TelegramError, Unauthorized
from telegram.utils.helpers import escape_markdown
from typing import Set, Dict, Any, Union

# --- Bot's Memory and Settings ---
POST_DELAY = 60  # Cooldown between posts for all users, in seconds
DELETE_COOLDOWN = 90  # Cooldown for deleting posts, in seconds
LINK_COOLDOWN = 14400 # 4 Hours cooldown for links

# Feature Toggles (True = Enabled, False = Disabled)
LINKS_ENABLED = True
PHOTOS_ENABLED = True

user_queues: Dict[int, datetime.datetime] = {}
user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {}

# --- Environment Variable Loading ---
try:
    TOKEN = os.environ['BOT_TOKEN']
    CHANNEL_ID = os.environ['CHANNEL_ID']
    OWNER_ID = int(os.environ['OWNER_ID'])
    LOG_CHANNEL_ID = os.environ['LOG_CHANNEL_ID']
except KeyError as e:
    print(f"Error: Missing critical environment variable {e}. Exiting.")
    sys.exit(1)
except ValueError:
    print("Error: OWNER_ID must be a valid integer ID. Exiting.")
    sys.exit(1)

# --- Persistence Loading ---

# 1. Banned Users
BANNED_USERS: Set[int] = set()
try:
    with open("banned_users.txt", "r") as f:
        BANNED_USERS = {int(line.strip()) for line in f if line.strip().isdigit()}
except FileNotFoundError: pass

# 2. Banned Words
BANNED_WORDS: Set[str] = set()
try:
    with open("banned_words.txt", "r") as f:
        BANNED_WORDS = {line.strip().lower() for line in f if line.strip()}
except FileNotFoundError: pass

# 3. Timeouts
USER_TIMEOUTS: Dict[int, float] = {}
try:
    with open("timeouts.txt", "r") as f:
        for line in f:
            if "," in line:
                uid, timestamp = line.strip().split(",")
                if float(timestamp) > datetime.datetime.now().timestamp():
                    USER_TIMEOUTS[int(uid)] = float(timestamp)
except FileNotFoundError: pass

# 4. Known Users (For Broadcast)
KNOWN_USERS: Set[int] = set()
try:
    with open("users.txt", "r") as f:
        KNOWN_USERS = {int(line.strip()) for line in f if line.strip().isdigit()}
except FileNotFoundError: pass

# States for ConversationHandler
AWAITING_HELP_MESSAGE = 0

# --- Helper Functions ---

def save_user(uid):
    """Saves a new user ID to the users.txt file if not already there."""
    if uid not in KNOWN_USERS:
        KNOWN_USERS.add(uid)
        with open("users.txt", "a") as f:
            f.write(f"{uid}\n")

def save_timeouts():
    with open("timeouts.txt", "w") as f:
        for uid, timestamp in USER_TIMEOUTS.items():
            if timestamp > datetime.datetime.now().timestamp():
                f.write(f"{uid},{timestamp}\n")

def check_for_banned_words(text: str) -> bool:
    if not text: return False
    text_lower = text.lower()
    for word in BANNED_WORDS:
        if word in text_lower:
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, text_lower) or text_lower == word:
                return True
    return False

def contains_link(message) -> bool:
    entities = (message.entities or []) + (message.caption_entities or [])
    return any(e.type in ('url', 'text_link') for e in entities)

def create_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    user_id = escape_markdown(str(job_info['user_id']), version=2)
    name = escape_markdown(job_info['user_name'], version=2)
    username = escape_markdown(job_info.get('username', 'N/A') or 'N/A', version=2)
    
    log_message = (
        f"*New {content_type} Confession Log*\n\n"
        f"*User ID:* `{user_id}`\n"
        f"*Name:* {name}\n"
        f"*Username:* @{username}\n\n"
    )
    
    content_to_log = text_content or job_info.get('caption')
    if content_to_log:
        log_message += f"*Content:*\n{escape_markdown(content_to_log, version=2)}"
    return log_message

# --- Job Queue Functions ---

def post_text(context):
    job_info = context.job.context
    context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'])
    log_message = create_log_message(job_info, "Text", text_content=job_info['text'])
    context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode='MarkdownV2')

def post_photo(context):
    job_info = context.job.context
    context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'])
    context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=job_info['caption'])
    log_message = create_log_message(job_info, "Photo")
    context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode='MarkdownV2')

# --- Handlers ---

def _schedule_post(update, context, post_type: str):
    user = update.message.from_user
    save_user(user.id) # Track user for broadcast
    
    if user.id in BANNED_USERS: return 

    # Photo Check
    if post_type == 'photo' and not PHOTOS_ENABLED:
        update.message.reply_text("Photo confessions are currently disabled by the administrator.")
        return

    if user.id in USER_TIMEOUTS:
        remaining = USER_TIMEOUTS[user.id] - datetime.datetime.now().timestamp()
        if remaining > 0:
            update.message.reply_text(f"Timeout active. {int(remaining/60)}m left.")
            return
        else:
            del USER_TIMEOUTS[user.id]
            save_timeouts()

    text_to_check = update.message.text if post_type == 'text' else (update.message.caption or "")
    if check_for_banned_words(text_to_check):
        update.message.reply_text("Banned word detected.")
        return

    # Link Check
    if contains_link(update.message):
        if not LINKS_ENABLED:
            update.message.reply_text("Links are currently disabled by the administrator.")
            return
        
        current_time = datetime.datetime.now()
        last_link_time = user_link_cooldowns.get(user.id)
        if last_link_time and (current_time - last_link_time).total_seconds() < LINK_COOLDOWN:
            remaining = LINK_COOLDOWN - (current_time - last_link_time).total_seconds()
            update.message.reply_text(f"Link limit: once every 4h. Wait {int(remaining/3600)}h {int((remaining%3600)/60)}m.")
            return
        user_link_cooldowns[user.id] = current_time

    delay = max(0, (user_queues.get(user.id, datetime.datetime.now()) - datetime.datetime.now()).total_seconds())
    
    job_context = {'chat_id': CHANNEL_ID, 'user_id': user.id, 'user_name': user.first_name, 'username': user.username}
    if post_type == 'text':
        job_context['text'] = text_to_check
        context.job_queue.run_once(post_text, delay, context=job_context)
    else:
        job_context['photo'] = update.message.photo[-1].file_id
        job_context['caption'] = text_to_check
        context.job_queue.run_once(post_photo, delay, context=job_context)

    user_queues[user.id] = datetime.datetime.now() + datetime.timedelta(seconds=delay + POST_DELAY)
    update.message.reply_text("Posted!" if delay == 0 else f"Queued ({int(delay)}s).")

def handle_confession(u, c): _schedule_post(u, c, 'text')
def handle_photo(u, c): _schedule_post(u, c, 'photo')

def handle_delete(update, context):
    user = update.message.from_user
    if user.id in BANNED_USERS or not update.message.forward_from_chat: return

    forwarded_chat_id = str(update.message.forward_from_chat.id)
    if forwarded_chat_id == str(CHANNEL_ID) or str(CHANNEL_ID).endswith(forwarded_chat_id):
        current_time = datetime.datetime.now()
        last_del = user_delete_cooldowns.get(user.id)
        if last_del and (current_time - last_del).total_seconds() < DELETE_COOLDOWN:
            update.message.reply_text(f"Wait {int(DELETE_COOLDOWN - (current_time - last_del).total_seconds())}s.")
            return

        try:
            msg_id = update.message.forward_from_message_id
            context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            user_delete_cooldowns[user.id] = current_time
            update.message.reply_text("Deleted.")
            
            log_txt = f"🗑 *DELETION LOG*\n*By:* {escape_markdown(user.first_name, 2)} (`{user.id}`)\n*Msg ID:* `{msg_id}`"
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_txt, parse_mode='MarkdownV2')
        except: update.message.reply_text("Could not delete. (Too old or already gone).")

# --- Admin & Broadcast ---

def toggle_links(update, context):
    if update.message.from_user.id != OWNER_ID: return
    global LINKS_ENABLED
    LINKS_ENABLED = not LINKS_ENABLED
    status = "Enabled" if LINKS_ENABLED else "Disabled"
    update.message.reply_text(f"Links are now {status}.")

def toggle_photos(update, context):
    if update.message.from_user.id != OWNER_ID: return
    global PHOTOS_ENABLED
    PHOTOS_ENABLED = not PHOTOS_ENABLED
    status = "Enabled" if PHOTOS_ENABLED else "Disabled"
    update.message.reply_text(f"Photos are now {status}.")

def broadcast(update, context):
    if update.message.from_user.id != OWNER_ID: return
    msg_text = " ".join(context.args)
    if not msg_text:
        update.message.reply_text("Usage: /broadcast <message>")
        return

    update.message.reply_text(f"Broadcasting to {len(KNOWN_USERS)} users...")
    sent, failed = 0, 0
    for uid in list(KNOWN_USERS):
        try:
            context.bot.send_message(chat_id=uid, text=msg_text)
            sent += 1
            time.sleep(0.05)
        except (Unauthorized, TelegramError): failed += 1
    update.message.reply_text(f"Done. ✅ {sent} | ❌ {failed}")

def timeout_user(update, context):
    if update.message.from_user.id != OWNER_ID: return
    try:
        target, mins = int(context.args[0]), int(context.args[1])
        USER_TIMEOUTS[target] = (datetime.datetime.now() + datetime.timedelta(minutes=mins)).timestamp()
        save_timeouts()
        update.message.reply_text(f"Timed out {target} for {mins}m.")
    except: update.message.reply_text("/timeout <id> <mins>")

def ban_user(update, context):
    if update.message.from_user.id != OWNER_ID: return
    try:
        target = int(context.args[0])
        BANNED_USERS.add(target)
        with open("banned_users.txt", "w") as f:
            for u in BANNED_USERS: f.write(f"{u}\n")
        update.message.reply_text(f"Banned {target}")
    except: update.message.reply_text("/ban <id>")

# --- User Commands ---

def start(update, context):
    save_user(update.message.from_user.id)
    update.message.reply_text("Welcome! Send a message or photo to confess. Use /guide for rules.")

def guide(update, context):
    txt = f"""
*Confession Guide*
@TapahConfession
- Forward a post back to me to delete it.
- **ADS:** You MUST include `#Ads` at the start of advertisement posts.
- **Restrictions:**
  - New post cooldown: 60s
  - Link cooldown: 4 hours {'(DISABLED)' if not LINKS_ENABLED else ''}
  - Delete cooldown: 90s
  - Photos: {'Enabled' if PHOTOS_ENABLED else 'Disabled'}
    """
    update.message.reply_text(txt, parse_mode='Markdown')

def help_command(update, context):
    update.message.reply_text("Send your query. It will be forwarded to the owner.")
    return AWAITING_HELP_MESSAGE

def forward_help(update, context):
    context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
    update.message.reply_text("Sent.")
    return ConversationHandler.END

def main():
    request_kwargs = {'read_timeout': 30, 'connect_timeout': 30}
    updater = Updater(TOKEN, use_context=True, request_kwargs=request_kwargs)
    dp = updater.dispatcher

    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={AWAITING_HELP_MESSAGE: [MessageHandler(Filters.all & ~Filters.command, forward_help)]},
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    ))

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("guide", guide))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("timeout", timeout_user))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("toggle_links", toggle_links))
    dp.add_handler(CommandHandler("toggle_photos", toggle_photos))
    dp.add_handler(CommandHandler("unban", lambda u, c: None)) 
    
    dp.add_handler(MessageHandler(Filters.forwarded, handle_delete))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_confession))

    updater.start_polling()
    updater.bot.send_message(chat_id=OWNER_ID, text="✅ Bot Online on Raspberry Pi!")
    updater.idle()

if __name__ == '__main__':
    main()
