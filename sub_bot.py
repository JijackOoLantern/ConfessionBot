import os
import sys
import time
import logging
import html
from telegram import LabeledPrice, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUB_BOT_TOKEN = os.environ.get('SUB_BOT_TOKEN')
OWNER_ID_STR = os.environ.get('OWNER_ID')
if not SUB_BOT_TOKEN or not OWNER_ID_STR:
    sys.exit(1)

OWNER_ID = int(OWNER_ID_STR)

# Defined Products
PRODUCTS = {
    'tier1': {'name': 'Tier 1 Premium (14 Days)', 'price': 100, 'desc': '30s queue, delete all, 14 days access.'},
    'tier2': {'name': 'Tier 2 Premium (14 Days)', 'price': 50, 'desc': '60s queue, long photo cd, 14 days access.'},
    'club': {'name': 'Club/Assoc Sub (30 Days)', 'price': 200, 'desc': 'Instant posting, no queue, 30 days access.'},
    'clear_timeout': {'name': 'Clear Timeout Pass', 'price': 50, 'desc': 'Instantly removes your active timeout.'}
}

AWAITING_CLUB_DETAILS = 1

def load_approved_clubs() -> set:
    clubs = set()
    try:
        if os.path.exists("approved_clubs.txt"):
            with open("approved_clubs.txt", "r", encoding="utf-8") as f:
                clubs = {int(line.strip()) for line in f if line.strip().isdigit()}
    except: pass
    return clubs

def save_approved_club(uid: int):
    clubs = load_approved_clubs()
    if uid not in clubs:
        with open("approved_clubs.txt", "a", encoding="utf-8") as f:
            f.write(f"{uid}\n")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"⭐ Tier 1 Premium - 100 Stars", callback_data='buy_tier1')],
        [InlineKeyboardButton(f"⭐ Tier 2 Premium - 50 Stars", callback_data='buy_tier2')],
        [InlineKeyboardButton(f"📝 Club Sub - Apply (Free)", callback_data='apply_club'),
         InlineKeyboardButton(f"⭐ Buy Club - 200 Stars", callback_data='buy_club')],
        [InlineKeyboardButton(f"🎟️ Clear Timeout Pass - 50 Stars", callback_data='buy_clear_timeout')]
    ]
    msg = (
        "🛒 <b>Welcome to the Tapah Store!</b>\n\n"
        "Purchase premium tiers or apply for verified Club access.\n"
        "<i>Note: Clubs must Apply and be approved by the Dev before they can Buy.</i>\n\n"
        "Select an item below:"
    )
    if update.message:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    if action.startswith('buy_'):
        prod_id = action.split('_', 1)[1]
        
        # Guard clause for Club Purchases
        if prod_id == 'club':
            approved_clubs = load_approved_clubs()
            if query.from_user.id not in approved_clubs and query.from_user.id != OWNER_ID:
                await query.answer("❌ You must Apply for a Club Sub and be approved by the Developer before purchasing!", show_alert=True)
                return ConversationHandler.END

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
        return ConversationHandler.END
        
    elif action == 'apply_club':
        await query.edit_message_text(
            "📝 <b>Club/Association Application</b>\n\n"
            "Please reply to this message with your <b>Club Name, Your Position, and Purpose</b>.\n"
            "<i>(Type /cancel to abort)</i>",
            parse_mode='HTML'
        )
        return AWAITING_CLUB_DETAILS
        
    elif action.startswith('approve_club_'):
        if query.from_user.id != OWNER_ID:
            await query.answer("Access Denied", show_alert=True)
            return ConversationHandler.END
            
        target_uid = int(action.split('_')[2])
        save_approved_club(target_uid)
            
        await query.edit_message_text(f"✅ Club access approved for User <code>{target_uid}</code>. They can now purchase it.", parse_mode='HTML')
        try:
            await context.bot.send_message(
                chat_id=target_uid, 
                text="🎉 <b>Application Approved!</b>\nYour Club application has been accepted by the Developer.\nYou can now purchase the Club Subscription for 200 Stars by typing /start and clicking '⭐ Buy Club'.", 
                parse_mode='HTML'
            )
        except Exception:
            pass
        return ConversationHandler.END
        
    elif action.startswith('reject_club_'):
        if query.from_user.id != OWNER_ID:
            await query.answer("Access Denied", show_alert=True)
            return ConversationHandler.END
            
        target_uid = int(action.split('_')[2])
        await query.edit_message_text(f"❌ Club access rejected for User <code>{target_uid}</code>.", parse_mode='HTML')
        try:
            await context.bot.send_message(
                chat_id=target_uid, 
                text="❌ <b>Application Rejected</b>\nYour request for Club Sub access has been declined by the Developer.", 
                parse_mode='HTML'
            )
        except Exception:
            pass
        return ConversationHandler.END

async def handle_club_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    details = update.message.text
    
    admin_msg = (
        f"📝 <b>New Club Application</b>\n\n"
        f"<b>User:</b> {user.first_name} (<code>{user.id}</code>)\n"
        f"<b>Username:</b> @{user.username}\n\n"
        f"<b>Details provided:</b>\n{html.escape(details)}"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_club_{user.id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_club_{user.id}")]
    ]
    await context.bot.send_message(chat_id=OWNER_ID, text=admin_msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        
    await update.message.reply_text("✅ Your application has been sent to the Developer. You will be notified once reviewed.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Application cancelled.")
    return ConversationHandler.END

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
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(button_handler, pattern='^(buy_|apply_club|approve_club_|reject_club_)')
        ],
        states={
            AWAITING_CLUB_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_club_details)]
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)]
    )
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(conv_handler)
    
    print("--- Sub Bot is Online ---")
    app.run_polling()

if __name__ == '__main__':
    main()
