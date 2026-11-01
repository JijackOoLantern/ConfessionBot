import os
import sys
import datetime
import time
import logging
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, PreCheckoutQueryHandler,
    MessageHandler, filters, CallbackQueryHandler, ContextTypes, Application
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(SCRIPT_DIR, '.env'))
except ImportError:
    pass

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    TOKEN = os.environ.get('SUB_BOT_TOKEN')
    OWNER_ID_STR = os.environ.get('OWNER_ID')
    LOG_CHANNEL_ID = os.environ.get('LOG_CHANNEL_ID')
    
    if not all([TOKEN, OWNER_ID_STR, LOG_CHANNEL_ID]):
        print("CRITICAL ERROR: Missing SUB_BOT_TOKEN, OWNER_ID, or LOG_CHANNEL_ID in .env")
        sys.exit(1)
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    print("CRITICAL ERROR: OWNER_ID must be a valid integer.")
    sys.exit(1)

# TIER DEFINITIONS FOR PURCHASING
# Format: Payload Name -> (Title, Description, Stars, Duration Days, Code)
PRODUCT_CATALOG = {
    'sub_tier_s': ("Sultan Tier", "14 Days Premium Access", 200, 14, 's'),
    'sub_tier_a': ("Along Tier", "14 Days Premium Access", 100, 14, 'a'),
    'sub_tier_b+': ("Bos Tier", "14 Days Premium Access", 50, 14, 'b+'),
    'sub_tier_c+': ("Club Tier", "30 Days Access (Approval Required)", 200, 30, 'c+'),
    'sub_tier_c': ("Cepat Kaya Tier", "14 Days Marketplace Bypass", 100, 14, 'c'),
    'clear_timeout': ("Clear Timeout Pass", "Instantly lift current timeout", 200, 0, 'none')
}

def load_timeouts():
    timeouts = {}
    try:
        if os.path.exists("timeouts.txt"):
            with open("timeouts.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if "," in line:
                        parts = line.strip().split(',', 2) 
                        uid = int(parts[0])
                        timestamp = float(parts[1])
                        reason = parts[2] if len(parts) > 2 else "No reason"
                        if float(timestamp) > time.time():
                            timeouts[uid] = {'expiry': timestamp, 'reason': reason}
    except: pass
    return timeouts

def save_timeouts(timeouts_dict):
    with open("timeouts.txt", "w", encoding="utf-8") as f:
        for uid, data in timeouts_dict.items():
            if data['expiry'] > time.time(): f.write(f"{uid},{data['expiry']},{data['reason']}\n")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🏬 <b>Welcome to the Tapah Subscriptions Store!</b>\n\n"
        "Purchase premium queue bypasses and elevated post limits instantly using Telegram Stars.\n\n"
        "<b>Available Plans:</b>\n"
        "👑 <b>Sultan (S)</b> - 200 Stars/14 Days\n"
        "🥇 <b>Along (A)</b> - 100 Stars/14 Days\n"
        "👔 <b>Bos (B+)</b> - 50 Stars/14 Days\n"
        "🛍️ <b>Cepat Kaya (C)</b> - 100 Stars/14 Days\n"
        "🏫 <b>Club (C+)</b> - 200 Stars/30 Days\n\n"
        "Select a product below to purchase:"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Sultan (200 Stars)", callback_data='buy_sub_tier_s')],
        [InlineKeyboardButton("🥇 Along (100 Stars)", callback_data='buy_sub_tier_a')],
        [InlineKeyboardButton("👔 Bos (50 Stars)", callback_data='buy_sub_tier_b+')],
        [InlineKeyboardButton("🛍️ Cepat Kaya (100 Stars)", callback_data='buy_sub_tier_c')],
        [InlineKeyboardButton("🏫 Club/Association (200 Stars)", callback_data='buy_sub_tier_c+')],
        [InlineKeyboardButton("🔓 Clear Timeout Pass (200 Stars)", callback_data='buy_clear_timeout')]
    ])
    await update.message.reply_text(msg, parse_mode='HTML', reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('buy_'):
        payload_id = query.data.replace('buy_', '')
        if payload_id not in PRODUCT_CATALOG: return
        
        title, desc, price, days, code = PRODUCT_CATALOG[payload_id]
        prices = [LabeledPrice(title, price)]
        
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=title,
            description=desc,
            payload=payload_id,
            provider_token="",  
            currency="XTR",     
            prices=prices
        )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload not in PRODUCT_CATALOG:
        await query.answer(ok=False, error_message="Product not found or unavailable.")
    else:
        await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    user = update.message.from_user
    uid = user.id
    
    if payload not in PRODUCT_CATALOG: return
    title, desc, price, days, code = PRODUCT_CATALOG[payload]
    
    if payload == 'clear_timeout':
        timeouts = load_timeouts()
        if uid in timeouts:
            del timeouts[uid]
            save_timeouts(timeouts)
            await update.message.reply_text("✅ <b>Timeout Cleared!</b> You can now use the bots again.", parse_mode='HTML')
            try: await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"🔓 <b>Timeout Cleared (Purchased)</b>\nUser: <code>{uid}</code>\nItem: {title}", parse_mode='HTML')
            except: pass
        else:
            await update.message.reply_text("✅ Purchase successful, but you didn't have an active timeout!")
    else:
        now = time.time()
        expiry = now + (days * 86400)
        with open("active_subscriptions.txt", "a", encoding="utf-8") as f:
            f.write(f"{uid},{code},{expiry}\n")
            
        await update.message.reply_text(f"🎉 <b>Purchase Successful!</b>\n\nYou are now subscribed to the <b>{title}</b> for {days} days.\nReturn to the main bot and check 'My Status' to see your new perks!", parse_mode='HTML')
        try: await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"💰 <b>New Subscription (Purchased)</b>\nUser: <code>{uid}</code>\nTier: {title} ({days} Days)\nPaid: {price} Stars", parse_mode='HTML')
        except: pass

async def post_init(application: Application):
    try: await application.bot.send_message(chat_id=OWNER_ID, text="✅ Subscription Store Bot is Online!")
    except: pass

def main():
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^buy_'))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    print("--- Subscription Store Bot is Online ---")
    application.run_polling()

if __name__ == '__main__':
    main()
