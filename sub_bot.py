import os
import sys
import time
import logging
from telegram import LabeledPrice, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUB_BOT_TOKEN = os.environ.get('SUB_BOT_TOKEN')
if not SUB_BOT_TOKEN:
    sys.exit(1)

# Defined Products
PRODUCTS = {
    'tier1': {'name': 'Tier 1 Premium (14 Days)', 'price': 100, 'desc': '15s queue, delete all, 14 days access.'},
    'tier2': {'name': 'Tier 2 Premium (14 Days)', 'price': 50, 'desc': '15s queue, long photo cd, 14 days access.'},
    'club': {'name': 'Club Sub (30 Days)', 'price': 200, 'desc': 'Instant posting, no queue, 30 days access.'},
    'clear_timeout': {'name': 'Clear Timeout Pass', 'price': 50, 'desc': 'Instantly removes your active timeout.'}
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"⭐ Tier 1 Premium - 100 Stars", callback_data='buy_tier1')],
        [InlineKeyboardButton(f"⭐ Tier 2 Premium - 50 Stars", callback_data='buy_tier2')],
        [InlineKeyboardButton(f"⭐ Club/Assoc Sub - 200 Stars", callback_data='buy_club')],
        [InlineKeyboardButton(f"🎟️ Clear Timeout Pass - 50 Stars", callback_data='buy_clear_timeout')]
    ]
    await update.message.reply_text(
        "🛒 <b>Welcome to the Tapah Store!</b>\n\n"
        "Purchase premium tiers or utility passes using Telegram Stars.\n"
        "Select an item below to receive an invoice:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    if action.startswith('buy_'):
        prod_id = action.split('_', 1)[1]
        if prod_id in PRODUCTS:
            prod = PRODUCTS[prod_id]
            title = prod['name']
            description = prod['desc']
            payload = f"TapahPurchase_{prod_id}_{query.from_user.id}"
            
            # Empty provider token + XTR currency triggers native Telegram Stars payment
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title=title,
                description=description,
                payload=payload,
                provider_token="",  
                currency="XTR",
                prices=[LabeledPrice(title, prod['price'])]
            )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("TapahPurchase_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Unknown payload.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    
    if payload.startswith("TapahPurchase_"):
        parts = payload.split('_')
        prod_id = parts[1]
        user_id = update.message.from_user.id
        
        if prod_id in ['tier1', 'tier2', 'club']:
            days = 14 if prod_id in ['tier1', 'tier2'] else 30
            expiry = time.time() + (days * 86400)
            
            with open("active_subscriptions.txt", "a", encoding="utf-8") as f:
                f.write(f"{user_id},{prod_id},{expiry}\n")
                
            await update.message.reply_text(f"✅ Payment successful! You have been granted {PRODUCTS[prod_id]['name']}.")
        
        elif prod_id == 'clear_timeout':
            # Instantly remove the user from the timeout file
            try:
                lines = []
                if os.path.exists("timeouts.txt"):
                    with open("timeouts.txt", "r", encoding="utf-8") as f:
                        lines = f.readlines()
                
                with open("timeouts.txt", "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.strip() and not line.startswith(f"{user_id},"):
                            f.write(line)
                            
                await update.message.reply_text("✅ Payment successful! Your timeout has been instantly cleared. You can now post again.")
            except Exception as e:
                await update.message.reply_text("✅ Payment successful, but an error occurred clearing the timeout. Please contact the Dev.")

def main():
    app = ApplicationBuilder().token(SUB_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    print("--- Sub Bot is Online ---")
    app.run_polling()

if __name__ == '__main__':
    main()
