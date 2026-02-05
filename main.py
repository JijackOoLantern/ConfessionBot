import os
import sys
import datetime
from telegram.ext import (
    Updater,
    MessageHandler,
    Filters,
    CommandHandler,
    ConversationHandler,
)
from telegram.error import BadRequest
from telegram.utils.helpers import escape_markdown
from typing import Set, Dict, Any, Union

# --- Bot's Memory and Settings ---
# Time settings
POST_DELAY = 60  # Cooldown between posts for all users, in seconds
DELETE_COOLDOWN = 90  # Cooldown for deleting posts, in seconds
LINK_COOLDOWN = 14400 # 4 Hours cooldown for links (4 * 60 * 60)

# In-memory storage for queues
user_queues: Dict[int, datetime.datetime] = {}
user_delete_cooldowns: Dict[int, datetime.datetime] = {}
user_link_cooldowns: Dict[int, datetime.datetime] = {} # New: Track link usage

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

# --- Persistence Loading (Bans & Timeouts) ---

# 1. Banned Users
BANNED_USERS: Set[int] = set()
try:
    with open("banned_users.txt", "r") as f:
        BANNED_USERS = {int(line.strip()) for line in f if line.strip().isdigit()}
except FileNotFoundError:
    print("banned_users.txt not found. Starting empty.")

# 2. Banned Words
BANNED_WORDS: Set[str] = set()
try:
    with open("banned_words.txt", "r") as f:
        BANNED_WORDS = {line.strip().lower() for line in f if line.strip()}
except FileNotFoundError:
    print("banned_words.txt not found. Starting empty.")

# 3. Timeouts (User ID -> Expiry Timestamp)
USER_TIMEOUTS: Dict[int, float] = {}
try:
    with open("timeouts.txt", "r") as f:
        for line in f:
            if "," in line:
                uid, timestamp = line.strip().split(",")
                # Only load if time hasn't passed yet
                if float(timestamp) > datetime.datetime.now().timestamp():
                    USER_TIMEOUTS[int(uid)] = float(timestamp)
except FileNotFoundError:
    print("timeouts.txt not found. Starting empty.")

# States for ConversationHandler
AWAITING_HELP_MESSAGE = 0

# --- Helper Functions ---

def save_timeouts():
    """Saves the current active timeouts to file."""
    with open("timeouts.txt", "w") as f:
        for uid, timestamp in USER_TIMEOUTS.items():
            # Only save if still valid
            if timestamp > datetime.datetime.now().timestamp():
                f.write(f"{uid},{timestamp}\n")

def check_for_banned_words(text: str) -> bool:
    """Checks if the given text contains any banned words."""
    if not text:
        return False
    text_lower = text.lower()
    for word in BANNED_WORDS:
        if word in text_lower:
            if text_lower == word:
                return True
            import re
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, text_lower):
                return True
    return False

def contains_link(message) -> bool:
    """Checks if the message or caption contains a URL entity."""
    # Check text body entities
    if message.entities:
        for entity in message.entities:
            if entity.type in ('url', 'text_link'):
                return True
    # Check photo caption entities
    if message.caption_entities:
        for entity in message.caption_entities:
            if entity.type in ('url', 'text_link'):
                return True
    return False

def create_log_message(job_info: Dict[str, Any], content_type: str, text_content: str = None) -> str:
    """Creates a crash-proof log message using MarkdownV2 escaping."""
    
    # Escape user inputs so weird names don't break the bot
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
        safe_content = escape_markdown(content_to_log, version=2)
        log_message += f"*Content:*\n{safe_content}"
        
    return log_message

# --- "Poster" Functions (JobQueue) ---

def post_text(context):
    """Job queue function to post text."""
    job_info = context.job.context
    text_to_post = job_info['text']
    
    # Post to Public Channel (Plain text, no parsing needed)
    context.bot.send_message(chat_id=job_info['chat_id'], text=text_to_post)
    
    # Post to Log Channel (MarkdownV2)
    log_message = create_log_message(job_info, "Text", text_content=text_to_post)
    context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode='MarkdownV2')

def post_photo(context):
    """Job queue function to post photo."""
    job_info = context.job.context
    
    # Post to Public Channel
    context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'])
    
    # --- LOGGING FIX: Separate photo from metadata ---
    # 1. Post to Log Channel - Send Photo first (with original caption)
    context.bot.send_photo(
        chat_id=LOG_CHANNEL_ID, 
        photo=job_info['photo'], 
        caption=job_info['caption']
    )

    # 2. Post Log Message as separate text message
    log_message = create_log_message(job_info, "Photo")
    context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode='MarkdownV2')


# --- "Handler" Functions ---

def _schedule_post(update, context, post_type: str):
    """Handles logic for checking bans, timeouts, and scheduling."""
    user = update.message.from_user
    user_id = user.id
    
    # 1. Ban Check
    if user_id in BANNED_USERS:
        return 

    # 2. Timeout Check
    if user_id in USER_TIMEOUTS:
        expiry = USER_TIMEOUTS[user_id]
        remaining = expiry - datetime.datetime.now().timestamp()
        if remaining > 0:
            minutes_left = int(remaining / 60)
            update.message.reply_text(f"You are in timeout for breaking rules. You can post again in {minutes_left} minutes.")
            return
        else:
            del USER_TIMEOUTS[user_id]
            save_timeouts()

    # Determine content
    text_to_check = ""
    if post_type == 'text':
        text_to_check = update.message.text
    elif post_type == 'photo':
        text_to_check = update.message.caption or ""
    
    # 3. Banned Words Check
    if check_for_banned_words(text_to_check):
        update.message.reply_text("Your message contains a banned word and was not posted.")
        return

    # 4. LINK COOLDOWN CHECK (New)
    if contains_link(update.message):
        current_time = datetime.datetime.now()
        last_link_time = user_link_cooldowns.get(user_id)
        
        if last_link_time:
            time_since_last = (current_time - last_link_time).total_seconds()
            if time_since_last < LINK_COOLDOWN:
                remaining_seconds = LINK_COOLDOWN - time_since_last
                hours_left = int(remaining_seconds / 3600)
                minutes_left = int((remaining_seconds % 3600) / 60)
                update.message.reply_text(f"Links are limited to once every 4 hours. Wait {hours_left}h {minutes_left}m.")
                return
        
        # Update the link timer if the check passed
        user_link_cooldowns[user_id] = current_time

    # 5. Queue Calculation
    current_time = datetime.datetime.now()
    last_post_time = user_queues.get(user_id, current_time)
    scheduled_time = max(current_time, last_post_time)
    delay = (scheduled_time - current_time).total_seconds()

    # Build Context
    job_context = {
        'chat_id': CHANNEL_ID,
        'user_id': user.id,
        'user_name': user.first_name,
        'username': user.username,
    }

    if post_type == 'text':
        job_context['text'] = text_to_check
        post_func = post_text
    elif post_type == 'photo':
        job_context['photo'] = update.message.photo[-1].file_id
        job_context['caption'] = text_to_check
        post_func = post_photo
        
    context.job_queue.run_once(post_func, delay, context=job_context)
    user_queues[user_id] = scheduled_time + datetime.timedelta(seconds=POST_DELAY)
    
    if delay > 0:
        update.message.reply_text(f"Your confession is in the queue and will be posted in about {int(delay)} seconds.")
    else:
        update.message.reply_text("Your confession has been posted anonymously.")

def handle_confession(update, context):
    _schedule_post(update, context, 'text')

def handle_photo_confession(update, context):
    _schedule_post(update, context, 'photo')

def handle_delete(update, context):
    """Handles deletion and logs who deleted what."""
    user = update.message.from_user
    user_id = user.id
    
    if user_id in BANNED_USERS: return

    # Check if forwarded from the correct channel
    if not update.message.forward_from_chat:
        update.message.reply_text("Please forward the *confession message* from the channel to delete it.")
        return

    forwarded_chat_id = str(update.message.forward_from_chat.id)
    target_id_str = str(CHANNEL_ID)
    
    if forwarded_chat_id == target_id_str or target_id_str.endswith(forwarded_chat_id) or forwarded_chat_id.endswith(target_id_str):
        
        # Cooldown check
        current_time = datetime.datetime.now()
        last_delete_time = user_delete_cooldowns.get(user_id)
        if last_delete_time:
            time_since_last = (current_time - last_delete_time).total_seconds()
            if time_since_last < DELETE_COOLDOWN:
                remaining = int(DELETE_COOLDOWN - time_since_last)
                update.message.reply_text(f"Cooldown active. Wait {remaining}s to delete again.")
                return

        message_id_to_delete = update.message.forward_from_message_id
        
        try:
            # 1. Delete
            context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id_to_delete)
            update.message.reply_text("The post has been deleted.")
            user_delete_cooldowns[user_id] = current_time
            
            # 2. Log the Deletion
            deleted_text = update.message.text or update.message.caption or "[Media with no caption]"
            safe_user = escape_markdown(f"{user.first_name} (ID: {user.id})", version=2)
            safe_content = escape_markdown(deleted_text, version=2)
            
            log_msg = (
                f"🗑 *DELETION LOG*\n"
                f"*Deleted By:* {safe_user}\n"
                f"*Msg ID:* `{message_id_to_delete}`\n"
                f"*Original Content:*\n{safe_content}"
            )
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_msg, parse_mode='MarkdownV2')
            
        except BadRequest as e:
            update.message.reply_text("Could not delete. Message might be too old (48h limit) or already deleted.")
            print(f"Delete Error: {e}")
        except Exception as e:
            update.message.reply_text("An error occurred.")
            print(f"Delete Error: {e}")
            
    else:
        update.message.reply_text("I can only delete posts from the official confession channel.")

# --- Admin Commands ---

def timeout_user(update, context):
    """(Owner) /timeout <user_id> <minutes>"""
    if update.message.from_user.id != OWNER_ID: return
    try:
        target_id = int(context.args[0])
        minutes = int(context.args[1])
        
        expiry_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        USER_TIMEOUTS[target_id] = expiry_time.timestamp()
        save_timeouts()
        
        update.message.reply_text(f"User {target_id} has been timed out for {minutes} minutes.")
    except (IndexError, ValueError):
        update.message.reply_text("Usage: /timeout <user_id> <minutes>")

def remove_timeout(update, context):
    """(Owner) /untimeout <user_id>"""
    if update.message.from_user.id != OWNER_ID: return
    try:
        target_id = int(context.args[0])
        if target_id in USER_TIMEOUTS:
            del USER_TIMEOUTS[target_id]
            save_timeouts()
            update.message.reply_text(f"Timeout removed for user {target_id}.")
        else:
            update.message.reply_text("User is not currently timed out.")
    except (IndexError, ValueError):
        update.message.reply_text("Usage: /untimeout <user_id>")

# Reuse existing moderation functions
def is_owner(uid): return uid == OWNER_ID

def ban_user(update, context):
    if not is_owner(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        if target == OWNER_ID: return
        BANNED_USERS.add(target)
        with open("banned_users.txt", "w") as f:
            for u in BANNED_USERS: f.write(f"{u}\n")
        update.message.reply_text(f"User {target} banned.")
    except: update.message.reply_text("Usage: /ban <id>")

def unban_user(update, context):
    if not is_owner(update.message.from_user.id): return
    try:
        target = int(context.args[0])
        BANNED_USERS.discard(target)
        with open("banned_users.txt", "w") as f:
            for u in BANNED_USERS: f.write(f"{u}\n")
        update.message.reply_text(f"User {target} unbanned.")
    except: update.message.reply_text("Usage: /unban <id>")

def add_banned_word(update, context):
    if not is_owner(update.message.from_user.id): return
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.add(word)
        with open("banned_words.txt", "w") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        update.message.reply_text(f"Banned: {word}")
    except: update.message.reply_text("Usage: /addban <word>")

def remove_banned_word(update, context):
    if not is_owner(update.message.from_user.id): return
    try:
        word = " ".join(context.args).lower()
        if not word: raise IndexError
        BANNED_WORDS.discard(word)
        with open("banned_words.txt", "w") as f:
            for w in BANNED_WORDS: f.write(f"{w}\n")
        update.message.reply_text(f"Unbanned: {word}")
    except: update.message.reply_text("Usage: /removeban <word>")

# --- User Commands ---
def start(update, context):
    update.message.reply_text("Welcome! Send a message to confess anonymously. Use /guide for rules.")

def guide(update, context):
    txt = """
*Confession Guide*
@TapahConfession
- Forward a post back to me to delete it.
- **ADS:** You MUST include `#Ads` at the start of advertisement posts.
- **Restrictions:**
  - New post cooldown: 60s
  - Link cooldown: 4 hours
  - Delete cooldown: 90s
  - No banned words allowed.
    """
    update.message.reply_text(txt, parse_mode='Markdown')

def clear_queue(update, context):
    if update.message.from_user.id in user_queues:
        del user_queues[update.message.from_user.id]
        update.message.reply_text("Queue cleared.")
    else:
        update.message.reply_text("Queue empty.")

def banned_words_list(update, context):
    msg = ", ".join(sorted(BANNED_WORDS)) if BANNED_WORDS else "None."
    update.message.reply_text(f"Banned words: {msg}")

# --- Help System ---
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

# --- Main ---
def main():
# Set the timeout to 30 seconds (default is usually 5-10)
    request_kwargs = {'read_timeout': 30, 'connect_timeout': 30}
    updater = Updater(TOKEN, use_context=True, request_kwargs=request_kwargs)
    dp = updater.dispatcher

    # Help Conv
    dp.add_handler(ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={AWAITING_HELP_MESSAGE: [MessageHandler(Filters.all & ~Filters.command, forward_help)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    ))

    # User Commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("guide", guide))
    dp.add_handler(CommandHandler("clearqueue", clear_queue))
    dp.add_handler(CommandHandler("bannedwords", banned_words_list))

    # Admin Commands
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("unban", unban_user))
    dp.add_handler(CommandHandler("addban", add_banned_word))
    dp.add_handler(CommandHandler("removeban", remove_banned_word))
    dp.add_handler(CommandHandler("timeout", timeout_user))
    dp.add_handler(CommandHandler("untimeout", remove_timeout))

    # Message Handlers
    dp.add_handler(MessageHandler(Filters.forwarded, handle_delete))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo_confession))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_confession))

    updater.start_polling()
    
    # --- STARTUP NOTIFICATION ---
    try:
        startup_message = f"✅ Bot is up! Running from Raspberry Pi. Started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        updater.bot.send_message(chat_id=OWNER_ID, text=startup_message)
    except Exception as e:
        print(f"Warning: Failed to send startup notification to owner: {e}")
        
    print("Bot is online with Link Cooldowns!")
    updater.idle()

if __name__ == '__main__':
    main()
