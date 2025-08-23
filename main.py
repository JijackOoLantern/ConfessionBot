import os
import datetime
from telegram.ext import (
    Updater,
    MessageHandler,
    Filters,
    CommandHandler,
    ConversationHandler,
)

# --- Bot's Memory and Settings ---
user_queues = {}
user_delete_cooldowns = {}
POST_DELAY = 15  # in seconds
DELETE_COOLDOWN = 60  # in seconds
OWNER_ID = os.environ.get('OWNER_ID')
LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')

# Load banned users from file
BANNED_USERS = set()
try:
    with open("banned_users.txt", "r") as f:
        BANNED_USERS = {int(line.strip()) for line in f if line.strip()}
except FileNotFoundError:
    print("banned_users.txt not found. Starting with an empty ban list.")

# Load banned words from file
BANNED_WORDS = set()
try:
    with open("banned_words.txt", "r") as f:
        BANNED_WORDS = {line.strip().lower() for line in f if line.strip()}
except FileNotFoundError:
    print("banned_words.txt not found. Starting with an empty banned words list.")

# States for ConversationHandler
AWAITING_HELP_MESSAGE = 0

# --- Telegram Bot Code ---
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID')

# --- Helper Functions ---
def check_for_banned_words(text):
    if not text:
        return False
    # Check against the loaded set of banned words
    for word in BANNED_WORDS:
        if word in text.lower():
            return True
    return False

# --- "Poster" Functions (called by the JobQueue) ---
def post_text(context):
    job_info = context.job.context
    context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'])
    log_message = (
        f"**New Text Confession Log**\n\n"
        f"**User ID:** `{job_info['user_id']}`\n"
        f"**Name:** {job_info['user_name']}\n"
        f"**Username:** @{job_info['username']}\n\n"
        f"**Confession:**\n{job_info['text']}"
    )
    context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode='Markdown')

def post_photo(context):
    job_info = context.job.context
    context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'])
    log_message = (
        f"**New Photo Confession Log**\n\n"
        f"**User ID:** `{job_info['user_id']}`\n"
        f"**Name:** {job_info['user_name']}\n"
        f"**Username:** @{job_info['username']}\n\n"
        f"**Caption:**\n{job_info['caption']}"
    )
    context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=log_message, parse_mode='Markdown')

# --- "Handler" Functions ---
def handle_confession(update, context):
    if update.message.from_user.id in BANNED_USERS: return
    confession_text = update.message.text
    if check_for_banned_words(confession_text):
        update.message.reply_text("Your message contains a banned word and was not posted.")
    else:
        user = update.message.from_user
        current_time = datetime.datetime.now()
        last_post_time = user_queues.get(user.id, current_time)
        scheduled_time = max(current_time, last_post_time)
        delay = (scheduled_time - current_time).total_seconds()
        job_context = {'chat_id': CHANNEL_ID, 'text': confession_text, 'user_id': user.id, 'user_name': user.first_name, 'username': user.username}
        context.job_queue.run_once(post_text, delay, context=job_context)
        user_queues[user.id] = scheduled_time + datetime.timedelta(seconds=POST_DELAY)
        if delay > 0:
            update.message.reply_text(f"Your confession is in the queue and will be posted in about {int(delay)} seconds.")
        else:
            update.message.reply_text("Your confession has been posted anonymously.")

def handle_photo_confession(update, context):
    if update.message.from_user.id in BANNED_USERS: return
    caption_text = update.message.caption
    if check_for_banned_words(caption_text):
        update.message.reply_text("Your caption contains a banned word and was not posted.")
    else:
        user = update.message.from_user
        current_time = datetime.datetime.now()
        last_post_time = user_queues.get(user.id, current_time)
        scheduled_time = max(current_time, last_post_time)
        delay = (scheduled_time - current_time).total_seconds()
        job_context = {'chat_id': CHANNEL_ID, 'photo': update.message.photo[-1].file_id, 'caption': caption_text, 'user_id': user.id, 'user_name': user.first_name, 'username': user.username}
        context.job_queue.run_once(post_photo, delay, context=job_context)
        user_queues[user.id] = scheduled_time + datetime.timedelta(seconds=POST_DELAY)
        if delay > 0:
            update.message.reply_text(f"Your photo is in the queue and will be posted in about {int(delay)} seconds.")
        else:
            update.message.reply_text("Your photo has been posted anonymously.")

def handle_delete(update, context):
    if update.message.from_user.id in BANNED_USERS: return
    user = update.message.from_user
    current_time = datetime.datetime.now()
    last_delete_time = user_delete_cooldowns.get(user.id)
    if last_delete_time:
        time_since_last_delete = (current_time - last_delete_time).total_seconds()
        if time_since_last_delete < DELETE_COOLDOWN:
            remaining_time = int(DELETE_COOLDOWN - time_since_last_delete)
            update.message.reply_text(f"You are on a cooldown. Please wait {remaining_time} more seconds to delete another post.")
            return
    if str(update.message.forward_from_chat.id) == CHANNEL_ID:
        message_id_to_delete = update.message.forward_from_message_id
        try:
            context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id_to_delete)
            update.message.reply_text("The post has been deleted.")
            user_delete_cooldowns[user.id] = current_time
        except Exception as e:
            update.message.reply_text("Could not delete the message. It might be too old.")
            print(f"Error deleting message: {e}")
    else:
        update.message.reply_text("I can only delete posts from the official confession channel.")

# --- Command Functions ---
def start(update, context):
    reply_message = "Welcome! Send a message or photo to post it anonymously. For more info, use /guide. Use /help to contact the owner."
    update.message.reply_text(reply_message)

def guide(update, context):
    guide_text = """
*Confession Guide*

This bot only supports text and images. Files are not supported.

To delete a message, just forward the confession from the channel back to me.

*!! Restrictions !!*
- New confessions have a 15-second cooldown per user to reduce spam.
- Deleting confessions has a 60-second cooldown to reduce abuse.
- Confessions with restricted words will not be posted.

_Updated: 23 Aug 2025_
    """
    update.message.reply_text(guide_text, parse_mode='Markdown')

def clear_queue(update, context):
    if update.message.from_user.id in BANNED_USERS: return
    user_id = update.message.from_user.id
    if user_id in user_queues:
        del user_queues[user_id]
        update.message.reply_text("Your queue has been cleared.")
    else:
        update.message.reply_text("You don't have anything in the queue.")

def banned_words(update, context):
    if not BANNED_WORDS:
        reply_message = "There are currently no banned words."
    else:
        word_list_string = ", ".join(BANNED_WORDS)
        reply_message = f"Banned words: {word_list_string}"
    update.message.reply_text(reply_message)

# --- Owner-Only Moderation Commands ---
def ban_user(update, context):
    if update.message.from_user.id != int(OWNER_ID): return
    try:
        user_to_ban = int(context.args[0])
        if user_to_ban == int(OWNER_ID):
            update.message.reply_text("You cannot ban yourself.")
            return
        BANNED_USERS.add(user_to_ban)
        with open("banned_users.txt", "w") as f:
            for user_id in BANNED_USERS: f.write(f"{user_id}\n")
        update.message.reply_text(f"User {user_to_ban} has been banned.")
    except (IndexError, ValueError):
        update.message.reply_text("Usage: /ban <user_id>")

def unban_user(update, context):
    if update.message.from_user.id != int(OWNER_ID): return
    try:
        user_to_unban = int(context.args[0])
        BANNED_USERS.discard(user_to_unban)
        with open("banned_users.txt", "w") as f:
            for user_id in BANNED_USERS: f.write(f"{user_id}\n")
        update.message.reply_text(f"User {user_to_unban} has been unbanned.")
    except (IndexError, ValueError):
        update.message.reply_text("Usage: /unban <user_id>")

def add_banned_word(update, context):
    if update.message.from_user.id != int(OWNER_ID): return
    try:
        word_to_add = context.args[0].lower()
        BANNED_WORDS.add(word_to_add)
        with open("banned_words.txt", "w") as f:
            for word in BANNED_WORDS: f.write(f"{word}\n")
        update.message.reply_text(f"The word '{word_to_add}' has been banned.")
    except IndexError:
        update.message.reply_text("Usage: /addban <word>")

def remove_banned_word(update, context):
    if update.message.from_user.id != int(OWNER_ID): return
    try:
        word_to_remove = context.args[0].lower()
        BANNED_WORDS.discard(word_to_remove)
        with open("banned_words.txt", "w") as f:
            for word in BANNED_WORDS: f.write(f"{word}\n")
        update.message.reply_text(f"The word '{word_to_remove}' has been unbanned.")
    except IndexError:
        update.message.reply_text("Usage: /removeban <word>")

# --- Help Conversation Functions ---
def help_command(update, context):
    if update.message.from_user.id in BANNED_USERS: return
    update.message.reply_text("Please send your question or problem. I will forward it anonymously to the owner. Use /cancel to exit.")
    return AWAITING_HELP_MESSAGE

def forward_help_message(update, context):
    context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
    update.message.reply_text("Your message has been sent to the owner. Thank you.")
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Help request cancelled.")
    return ConversationHandler.END

# --- Main Bot Setup ---
def main():
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={AWAITING_HELP_MESSAGE: [MessageHandler(Filters.all & ~Filters.command, forward_help_message)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    dispatcher.add_handler(conv_handler)

    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("guide", guide))
    dispatcher.add_handler(CommandHandler("clearqueue", clear_queue))
    dispatcher.add_handler(CommandHandler("bannedwords", banned_words))
    dispatcher.add_handler(CommandHandler("ban", ban_user))
    dispatcher.add_handler(CommandHandler("unban", unban_user))
    dispatcher.add_handler(CommandHandler("addban", add_banned_word))
    dispatcher.add_handler(CommandHandler("removeban", remove_banned_word))

    # Add message handlers
    dispatcher.add_handler(MessageHandler(Filters.forwarded, handle_delete))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo_confession))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_confession))

    updater.start_polling()
    print("Bot is fully online with all features!")
    updater.idle()

if __name__ == '__main__':
    main()