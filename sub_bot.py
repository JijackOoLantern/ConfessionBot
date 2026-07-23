import os
import sys
import time
import datetime
import logging
import html
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from typing import Dict, Union

# --- Live Terminal Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TIMEZONE = pytz.timezone('Asia/Kuala_Lumpur')

try:
    SUB_BOT_TOKEN = os.environ.get('SUB_BOT_TOKEN')
    OWNER_ID = int(os.environ.get('OWNER_ID'))
    if not SUB_BOT_TOKEN:
        print("❌ CRITICAL ERROR: Missing SUB_BOT_TOKEN in .env file.")
        sys.exit(1)
except Exception as e:
    print(f"❌ Configuration Error: {e}")
    sys.exit(1)

action_states: Dict[int, str] = {}

# --- Human-Readable Duration Formatter ---
def format_duration(seconds: Union[int, float]) -> str:
    seconds = int(seconds)
    if seconds <= 0:
        return "0 seconds"
    if seconds < 60:
        return f"{seconds} second" + ("s" if seconds != 1 else "")
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
    if minutes > 0:
        parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
    if secs > 0 and hours == 0:
        parts.append(f"{secs} second" + ("s" if secs > 1 else ""))
        
    return " ".join(parts)

# --- LIVE Pricing & Tier Configurations ---
TIER_CONFIG = {
    'basic': {
        'name': 'Normal User (Default)',
        'link_cooldown': 14400,   
        'photo_cooldown': 14400,  
        'personal_queue_duration': 30,      
        'delete_cooldown': 60,  
        'delete_access': 'own',
        'price': 0,
        'duration_days': 0
    },
    'tier1': {
        'name': 'Tier 1 Premium',
        'link_cooldown': 14400,   
        'photo_cooldown': 14400,  
        'personal_queue_duration': 15,      
        'delete_cooldown': 30,    
        'delete_access': 'all',
        'price': 100,             # Restored Production Price: 100 Stars
        'duration_days': 14   
    },
    'tier2': {
        'name': 'Tier 2 Premium',
        'link_cooldown': 14400,   
        'photo_cooldown': 21600,  
        'personal_queue_duration': 15,      
        'delete_cooldown': 60,    
        'delete_access': 'all',
        'price': 50,              # Restored Production Price: 50 Stars
        'duration_days': 14   
    },
    'club': {
        'name': 'Club/Association Sub',
        'link_cooldown': 3600,    
        'photo_cooldown': 3600,   
        'personal_queue_duration': 15,      
        'delete_cooldown': 0,     
        'delete_access': 'own',
        'price': 200,             # Restored Production Price: 200 Stars
        'duration_days': 30   
    }
}

PERK_CONFIG = {
    'spotlight': {
        'name': 'Spotlight Perk',
        'desc': 'Instantly skips the post queue',
        'price': 100,             # Restored Production Price: 100 Stars
        'duration_hours': 12  
    },
    'immunity': {
        'name': 'Immunity Perk',
        'desc': 'Protects your post from being deleted by others',
        'price': 100,             # Restored Production Price: 100 Stars
        'duration_hours': 12  
    }
}

GUIDE_TEXT = (
    "<b>UiTM Tapah Confession Bot Guide and Conditions.</b>\n\n"
    "<u>User</u>\n"
    "- Any user of the bot will get Basic Level of Subscription. To get advanced level access, read subscription.\n\n"
    "<u>Posts</u>\n"
    "- Posts are anonymous.\n"
    "- All posts will be queued according to their level of subscription. Meaning many user = long queue. This is to reduce spamming an collectively be mindful of our interaction.\n\n"
    "For example Basic Level. User A need to wait for 30 seconds before it's confession being posted. User B who posts immediately after User A, will need to wait for 60 seconds before it's confession being posted. User A queue 30 seconds + own queue 30 seconds.\n\n"
    "<u>Deletion</u>\n"
    "- To delete a post, forward the message to the bot.\n"
    "- A timeout will be imposed for any users who send \"delete\" (not case sensitive)\n\n"
    "<u>Queue Time</u>\n"
    "- Queue time is to replace cooldown.\n"
    "- Queue time is bound by level of subscription.\n\n"
    "<u>Timeout</u>\n"
    "- Timed punishment for user imposed by Dev/Mod, with the reason of posting unpleasant posts.\n\n"
    "<u>Subscription/Perks</u>\n"
    "- Optional add-on to improve bot user interaction.\n"
    "- Subscription Based.\n"
    "- No refund will be issued.\n\n"
    "<u>Subscription for Clubs</u>\n"
    "- Only 2 accounts allowed for any clubs & association\n"
    "- Strictly only for clubs related posts\n"
    "- Any post made in the interest of personal related will risk the access to subscription revoked and will not be refunded.\n\n"
    "<u>Developer/Moderator (Dev/Mod)</u>\n"
    "- Developer is the one who develop the bot and the channel.\n"
    "- Moderator is the one who manages the channel with their own willingness.\n"
    "- Any decision made by the Dev and Mod is with their own level of judgement and should not be questioned.\n\n"
    "<u>Mature Content</u>\n"
    "- Any posts showing clear signs of mature content that risks the banning of the channel, will be deleted and the sender of the post will be banned and no appeal will be heard.\n\n"
    "<u>Banned Words/User</u>\n"
    "- Any words that is banned will not be posted. The list is updated periodically.\n"
    "- Banned user is allowed to appeal with the judgement of Dev.\n"
    "- User that is banned with the request of Mod is not allowed to appeal."
)

def get_user_tier(uid: int) -> str:
    if uid == OWNER_ID: return 'tier1'
    try:
        if os.path.exists("active_subscriptions.txt"):
            with open("active_subscriptions.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        user_str, tier, expiry_str = line.strip().split(',')
                        if int(user_str) == uid and float(expiry_str) > time.time():
                            return tier
    except Exception: pass
    return 'basic'

def get_active_perks(uid: int) -> set:
    perks = set()
    try:
        if os.path.exists("active_perks.txt"):
            with open("active_perks.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        user_str, perk, expiry_str = line.strip().split(',')
                        if int(user_str) == uid and float(expiry_str) > time.time():
                            perks.add(perk)
    except Exception: pass
    return perks

def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Subscription Store", callback_data='nav_store')],
        [InlineKeyboardButton("👤 My Active Status", callback_data='nav_status')],
        [InlineKeyboardButton("📖 Pricing & Perks Summary", callback_data='nav_summary')],
        [InlineKeyboardButton("📋 Full Rules & Operational Guide", callback_data='nav_guide')]
    ])

def get_store_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎫 Tier 1 Premium (100 ⭐️)", callback_data='buy_tier1')],
        [InlineKeyboardButton("🎫 Tier 2 Premium (50 ⭐️)", callback_data='buy_tier2')],
        [InlineKeyboardButton("🏢 Club Sub (200 ⭐️)", callback_data='buy_club')],
        [InlineKeyboardButton("⚡ Spotlight Perk (100 ⭐️)", callback_data='buy_spotlight')],
        [InlineKeyboardButton("🛡️ Immunity Perk (100 ⭐️)", callback_data='buy_immunity')],
        [InlineKeyboardButton("◀️ Back to Main Menu", callback_data='nav_main')]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_txt = (
        "👋 <b>Welcome to the Tapah Subscription & Perks Portal!</b>\n\n"
        "Here you can upgrade your account tier or purchase single-use perks using Telegram Stars (⭐️).\n\n"
        "All purchases are automatically synchronized with the Confession Bot instantly!"
    )
    await update.message.reply_text(welcome_txt, parse_mode='HTML', reply_markup=get_main_keyboard())

async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command for owner/dev to revoke a user subscription with reasoning."""
    if not update.message or update.message.from_user.id != OWNER_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Format: <code>/revoke <user_id> <reason></code>", parse_mode='HTML')
        return
    try:
        target_uid = int(context.args[0])
        reason = " ".join(context.args[1:])
        
        revoked = False
        remaining_lines = []
        if os.path.exists("active_subscriptions.txt"):
            with open("active_subscriptions.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and "," in line:
                        u_id, tier, expiry = line.strip().split(',')
                        if int(u_id) == target_uid:
                            revoked = True
                        else:
                            remaining_lines.append(line)
                            
        if revoked:
            with open("active_subscriptions.txt", "w", encoding="utf-8") as f:
                f.writelines(remaining_lines)
            
            await update.message.reply_text(f"✅ Subscription for user <code>{target_uid}</code> has been REVOKED.", parse_mode='HTML')
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"⚠️ <b>Subscription Revoked</b>\n\nYour subscription access has been revoked by the Developer.\n<b>Reason:</b> {html.escape(reason)}",
                    parse_mode='HTML'
                )
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not notify user {target_uid} directly: {e}")
        else:
            await update.message.reply_text(f"⚠️ No active subscription found for user <code>{target_uid}</code>.", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ User ID must be a valid number.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == 'nav_main':
        if uid in action_states: del action_states[uid]
        welcome_txt = (
            "👋 <b>Welcome to the Tapah Subscription & Perks Portal!</b>\n\n"
            "Select an option from the menu below:"
        )
        await query.edit_message_text(welcome_txt, parse_mode='HTML', reply_markup=get_main_keyboard())

    elif query.data == 'nav_store':
        store_txt = (
            "🛒 <b>Subscription & Perks Storefront</b>\n\n"
            "Choose a tier or perk below to complete your payment with Telegram Stars (⭐️):"
        )
        await query.edit_message_text(store_txt, parse_mode='HTML', reply_markup=get_store_keyboard())

    elif query.data == 'nav_status':
        tier = get_user_tier(uid)
        perks = get_active_perks(uid)
        
        perk_names = [PERK_CONFIG[p]['name'] for p in perks if p in PERK_CONFIG]
        perk_str = ", ".join(perk_names) if perk_names else "None"
        cfg = TIER_CONFIG.get(tier, TIER_CONFIG['basic'])
        
        status_txt = (
            f"👤 <b>Runtime Profile Audit</b>\n\n"
            f"🎫 <b>Owned Access Tier:</b> <code>{cfg['name']}</code>\n"
            f"⚡ <b>Owned Active Perks:</b> <code>{perk_str}</code>\n\n"
            f"📊 <b>Active Tier Privileges:</b>\n"
            f"• Personal Queue Duration: <code>{format_duration(cfg['personal_queue_duration'])}</code>\n"
            f"• Photo/Link Limit: <code>{format_duration(cfg['photo_cooldown'])}</code>\n"
            f"• Deletion Access: <code>{cfg['delete_access'].title()} posts</code>\n"
            f"• Deletion Cooldown: <code>{format_duration(cfg['delete_cooldown'])}</code>"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='nav_main')]])
        await query.edit_message_text(status_txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'nav_summary':
        guide_txt = (
            "📖 <b>Subscription & Perks Summary</b>\n\n"
            "<b>Normal User (Default)</b>\n- 30s personal queue duration\n- 4h photo & link limit\n- Delete own posts only\n\n"
            "<b>Tier 1 (100 ⭐️ / 14 Days)</b>\n- 15s personal queue duration\n- 4h photo & link limit\n- Delete own & others posts\n\n"
            "<b>Tier 2 (50 ⭐️ / 14 Days)</b>\n- 15s personal queue duration\n- 4h link / 6h photo limit\n- Delete own & others posts\n\n"
            "<b>Club Sub (200 ⭐️ / 30 Days)</b>\n- 15s personal queue duration\n- 1h photo & link limit\n- Instant deletion access\n\n"
            "<b>Spotlight Perk (100 ⭐️ / 12 Hours)</b>\n- Bypasses active queue delays\n\n"
            "<b>Immunity Perk (100 ⭐️ / 12 Hours)</b>\n- Prevents non-admins from deleting post"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='nav_main')]])
        await query.edit_message_text(guide_txt, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'nav_guide':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data='nav_main')]])
        await query.edit_message_text(GUIDE_TEXT, parse_mode='HTML', reply_markup=markup)

    elif query.data == 'buy_club':
        action_states[uid] = 'awaiting_club_name'
        verify_txt = (
            "🏢 <b>Club Subscription Request</b>\n\n"
            "Before purchasing this tier, we need to verify your association.\n"
            "Please type and send the official name of your Club/Association below. This will be sent to the Developer for approval."
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancel", callback_data='nav_main')]])
        await query.edit_message_text(verify_txt, parse_mode='HTML', reply_markup=markup)

    elif query.data.startswith('buy_'):
        item_code = query.data.replace('buy_', '')
        title = ""
        description = ""
        price_stars = 0

        if item_code in TIER_CONFIG:
            title = TIER_CONFIG[item_code]['name']
            description = f"Upgrade your account to {title} for {TIER_CONFIG[item_code]['duration_days']} days."
            price_stars = TIER_CONFIG[item_code]['price']
        elif item_code in PERK_CONFIG:
            title = PERK_CONFIG[item_code]['name']
            description = PERK_CONFIG[item_code]['desc']
            price_stars = PERK_CONFIG[item_code]['price']

        prices = [LabeledPrice(title, price_stars)]

        try:
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title=title,
                description=description,
                payload=f"purchase_{item_code}",
                provider_token="",  
                currency="XTR",     
                prices=prices
            )
        except Exception as e:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Payment Failed: {e}")

    elif query.data.startswith('approve_club_'):
        target_uid = int(query.data.split('_')[2])
        await query.edit_message_text(f"{query.message.text}\n\n<b>Status:</b> ✅ APPROVED")
        
        title = TIER_CONFIG['club']['name']
        description = f"Upgrade your account to {title} for {TIER_CONFIG['club']['duration_days']} days."
        prices = [LabeledPrice(title, TIER_CONFIG['club']['price'])]
        try:
            await context.bot.send_message(
                chat_id=target_uid, 
                text="🎉 Your Club/Association request has been <b>APPROVED</b>! You can now complete your subscription using the invoice below:", 
                parse_mode='HTML'
            )
            await context.bot.send_invoice(
                chat_id=target_uid,
                title=title,
                description=description,
                payload="purchase_club",
                provider_token="",
                currency="XTR",
                prices=prices
            )
        except Exception as e:
            await context.bot.send_message(chat_id=OWNER_ID, text=f"Failed to send invoice to user {target_uid}: {e}")

    elif query.data.startswith('reject_club_'):
        target_uid = int(query.data.split('_')[2])
        action_states[OWNER_ID] = f"reject_club_reason_{target_uid}"
        await query.edit_message_text(f"{query.message.text}\n\n<b>Status:</b> 📝 Awaiting Rejection Reason...")
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"Please send the reason for declining Club User <code>{target_uid}</code> below:"
        )

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches text input for Club Verification and Rejection Reasoning."""
    if not update.message or not update.message.from_user: return
    user = update.message.from_user
    uid = user.id
    
    if action_states.get(uid) == 'awaiting_club_name':
        club_name = update.message.text
        del action_states[uid]
        
        await update.message.reply_text("✅ Your request has been sent to the Developer for approval. You will receive a notification once reviewed.")
        
        username_str = f"@{html.escape(user.username)}" if user.username else "No username set"
        full_name_str = html.escape(user.full_name)
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_club_{uid}"), 
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_club_{uid}")]
        ])
        await context.bot.send_message(
            chat_id=OWNER_ID, 
            text=(
                f"🆕 <b>Club Verification Request</b>\n\n"
                f"<b>User ID:</b> <code>{uid}</code>\n"
                f"<b>Name:</b> {full_name_str}\n"
                f"<b>Username:</b> {username_str}\n"
                f"<b>Club Name:</b> <b>{html.escape(club_name)}</b>\n\n"
                f"Do you approve this club for a subscription?"
            ),
            parse_mode='HTML', 
            reply_markup=markup
        )
    
    elif uid == OWNER_ID and action_states.get(uid, "").startswith("reject_club_reason_"):
        target_uid = int(action_states[uid].replace("reject_club_reason_", ""))
        reason = update.message.text
        del action_states[uid]
        
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"❌ Your Club/Association request has been declined by the Developer.\n<b>Reason:</b> {html.escape(reason)}",
                parse_mode='HTML'
            )
            await update.message.reply_text(f"✅ Rejection reason delivered to user <code>{target_uid}</code>.", parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to notify user {target_uid}: {e}")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("purchase_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Invalid purchase token.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    payload = update.message.successful_payment.invoice_payload
    item_code = payload.replace("purchase_", "")
    now = time.time()

    if item_code in TIER_CONFIG:
        duration_seconds = TIER_CONFIG[item_code]['duration_days'] * 86400
        expiry = now + duration_seconds
        with open("active_subscriptions.txt", "a", encoding="utf-8") as f:
            f.write(f"{user_id},{item_code},{expiry}\n")
        await update.message.reply_text(
            f"🎉 <b>Payment Successful!</b>\nYour account has been upgraded to <b>{TIER_CONFIG[item_code]['name']}</b>!", 
            parse_mode='HTML'
        )

    elif item_code in PERK_CONFIG:
        duration_seconds = PERK_CONFIG[item_code]['duration_hours'] * 3600
        expiry = now + duration_seconds
        with open("active_perks.txt", "a", encoding="utf-8") as f:
            f.write(f"{user_id},{item_code},{expiry}\n")
        await update.message.reply_text(
            f"⚡ <b>Payment Successful!</b>\nActivated perk: <b>{PERK_CONFIG[item_code]['name']}</b>!", 
            parse_mode='HTML'
        )

def main():
    application = ApplicationBuilder().token(SUB_BOT_TOKEN).read_timeout(30).connect_timeout(30).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("revoke", revoke_command))
    application.add_handler(CallbackQueryHandler(callback_handler, pattern='^(nav_|buy_|approve_club_|reject_club_)'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    print("--- Cashier Subscription Bot is Online ---")
    application.run_polling()

if __name__ == '__main__':
    main()
