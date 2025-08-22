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
POST_DELAY = 15
BANNED_WORDS = ["VGK", "CP", "word3"] # <-- Add your banned words
OWNER_ID = os.environ.get('OWNER_ID')
LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID') # For private logging
user_delete_cooldowns = {} # For the delete function cooldown
DELETE_COOLDOWN = 60 # Cooldown in seconds (e.g., 30 seconds)

# States for ConversationHandler
AWAITING_HELP_MESSAGE = 0


# --- Telegram Bot Code ---
TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID')

# --- Helper Functions ---
def check_for_banned_words(text):
    if not text:
        return False
    for word in BANNED_WORDS:
        if word in text.lower():
            return True
    return False

# --- "Poster" Functions (called by the JobQueue) ---
def post_text(context):
    """Posts the text to the public channel and sends a log."""
    job_info = context.job.context
    context.bot.send_message(chat_id=job_info['chat_id'], text=job_info['text'])

    log_message = (
        f"**New Text Confession Log**\n\n"
        f"**User ID:** `{job_info['user_id']}`\n"
        f"**Name:** {job_info['user_name']}\n\n"
        f"**Username:** {job_info['username']}\n\n"
        f"**Confession:**\n{job_info['text']}"
    )
    context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode='Markdown')

def post_photo(context):
    """Posts the photo to the public channel and sends a log."""
    job_info = context.job.context
    context.bot.send_photo(chat_id=job_info['chat_id'], photo=job_info['photo'], caption=job_info['caption'])

    log_message = (
        f"**New Photo Confession Log**\n\n"
        f"**User ID:** `{job_info['user_id']}`\n"
        f"**Name:** {job_info['user_name']}\n\n"
        f"**Username:** {job_info['username']}\n\n"
        f"**Caption:**\n{job_info['caption']}"
    )
    context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=job_info['photo'], caption=log_message, parse_mode='Markdown')


# --- "Handler" Functions ---
def handle_confession(update, context):
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
    """Deletes a post when it's forwarded, with a cooldown."""
    user = update.message.from_user
    current_time = datetime.datetime.now()

    # --- Cooldown Check ---
    last_delete_time = user_delete_cooldowns.get(user.id)
    if last_delete_time:
        time_since_last_delete = (current_time - last_delete_time).total_seconds()
        if time_since_last_delete < DELETE_COOLDOWN:
            remaining_time = int(DELETE_COOLDOWN - time_since_last_delete)
            update.message.reply_text(f"You are on a cooldown. Please wait {remaining_time} more seconds.")
            return # Stop the function here
    # --- End of Cooldown Check ---

    # If not on cooldown, proceed with deletion logic
    if str(update.message.forward_from_chat.id) == CHANNEL_ID:
        message_id_to_delete = update.message.forward_from_message_id
        try:
            context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id_to_delete)
            update.message.reply_text("The post has been deleted.")
            # Update the user's last delete time
            user_delete_cooldowns[user.id] = current_time
        except Exception as e:
            update.message.reply_text("Could not delete the message. It might be too old or I may lack permissions.")
            print(f"Error deleting message: {e}") # For your own logs
    else:
        update.message.reply_text("I can only delete posts from the official confession channel.")

# --- Command Functions ---
def start(update, context):
    reply_message = "Welcome to the Confession Bot! Send me a message or a photo, and I will post it anonymously to the https://t.me/TapahConfession. Use /help to contact the owner."
    update.message.reply_text(reply_message)

def clear_queue(update, context):
    user_id = update.message.from_user.id
    if user_id in user_queues:
        del user_queues[user_id]
        update.message.reply_text("Your queue has been cleared.")
    else:
        update.message.reply_text("You don't have anything in the queue.")

def banned_words(update, context):
    word_list_string = ", ".join(BANNED_WORDS)
    reply_message = f"Banned words: {word_list_string}"
    update.message.reply_text(reply_message)

# --- Help Conversation Functions ---
def help_command(update, context):
    update.message.reply_text("Please send your question or problem. I will forward it anonymously to the owner.")
    return AWAITING_HELP_MESSAGE

def forward_help_message(update, context):
    context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
    update.message.reply_text("Your message has been sent to the owner. Thank you.")
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Help request cancelled.")
    return ConversationHandler.END

def guide(update, context):
    """Sends the user a guide on how to use the bot."""
    guide_text = """
*Confession Guide*

This bot only supports text and images. Files are not supported.

To delete a message, just forward the confession from the channel back to me.

*!! Restrictions !!*
- New confessions have a 60-second cooldown per user to reduce spam.
- Deleting confessions has a 30-second cooldown to reduce abuse.
- Confessions with restricted words will not be posted.

_Updated: 22 Aug 2025_
    """
    update.message.reply_text(guide_text, parse_mode='Markdown')

# --- Main Bot Setup ---
def main():
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('help', help_command)],
        states={
            AWAITING_HELP_MESSAGE: [MessageHandler(Filters.text | Filters.photo, forward_help_message)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    dispatcher.add_handler(conv_handler)

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("clearqueue", clear_queue))
    dispatcher.add_handler(CommandHandler("bannedwords", banned_words))
    dispatcher.add_handler(CommandHandler("guide", guide))

    dispatcher.add_handler(MessageHandler(Filters.forwarded, handle_delete))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo_confession))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_confession))

    updater.start_polling()
    print("Bot is fully online with all features, including private logging!")
    updater.idle()

if __name__ == '__main__':
    main()