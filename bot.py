import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread
import logging

# --- LOGGING (Helpful for debugging on Render) ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): 
    return "✅ Telegram Stars Subscription Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# --- CONFIGURATION (Environment Variables) ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME', '')  # Optional for support button

if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
    logger.error("Missing required environment variables: BOT_TOKEN, MONGO_URI, ADMIN_ID")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']

# --- ADMIN LOGIC (Mostly unchanged) ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    text = message.text.split()

    # User entry via Deep Link (e.g. t.me/bot?start=CHANNEL_ID)
    if len(text) > 1:
        try:
            ch_id = int(text[1])
            ch_data = channels_col.find_one({"channel_id": ch_id})
            if ch_data:
                markup = InlineKeyboardMarkup()
                # Display Dynamic Plans - UPDATED FOR STARS
                for p_time, p_price in ch_data['plans'].items():
                    mins = int(p_time)
                    if mins < 60:
                        label = f"{mins} Minutes"
                    elif mins < 1440:
                        label = f"{mins // 60} Hours"
                    else:
                        label = f"{mins // 1440} Days"
                    
                    # Price is now in Stars (no ₹)
                    markup.add(InlineKeyboardButton(
                        f"⭐ {label} - {p_price} Stars", 
                        callback_data=f"select_{ch_id}_{p_time}"
                    ))
                
                if CONTACT_USERNAME:
                    markup.add(InlineKeyboardButton("📞 Contact Support", url=f"https://t.me/{CONTACT_USERNAME}"))
                
                bot.send_message(
                    message.chat.id, 
                    f"👋 Welcome!\n\nYou are joining: *{ch_data['name']}*.\n\nPlease select a subscription plan below:\n\n"
                    "💡 *How it works:*\n"
                    "• Pay with Telegram Stars (instant & automatic)\n"
                    "• Get temporary access via invite link\n"
                    "• Auto-removed when subscription expires\n"
                    "• Renew anytime!", 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
                return
        except Exception as e:
            logger.error(f"Deep link error: {e}")
            pass

    # Admin Panel Greeting
    if user_id == ADMIN_ID:
        bot.send_message(
            message.chat.id, 
            "✅ *Admin Panel Active!*\n\n"
            "Commands:\n"
            "/add - Add or update a channel & its plans\n"
            "/channels - List & manage your channels\n\n"
            "💡 After adding a channel, share the invite link with users:\n"
            "`https://t.me/" + bot.get_me().username + "?start=CHANNEL_ID`", 
            parse_mode="Markdown"
        )
    else:
        # For normal users: Automatically show plans of available channels
        channels = list(channels_col.find({}))
        if channels:
            # Show plans from the first channel (you can expand this later for multiple channels)
            ch_data = channels[0]
            ch_id = ch_data['channel_id']
            
            markup = InlineKeyboardMarkup()
            for p_time, p_price in ch_data['plans'].items():
                mins = int(p_time)
                if mins < 60:
                    label = f"{mins} Minutes"
                elif mins < 1440:
                    label = f"{mins // 60} Hours"
                else:
                    label = f"{mins // 1440} Days"
                
                markup.add(InlineKeyboardButton(
                    f"⭐ {label} - {p_price} Stars", 
                    callback_data=f"select_{ch_id}_{p_time}"
                ))
            
            if CONTACT_USERNAME:
                markup.add(InlineKeyboardButton("📞 Contact Support", url=f"https://t.me/{CONTACT_USERNAME}"))
            
            bot.send_message(
                message.chat.id, 
                f"👋 *Welcome!*\n\n"
                f"You are joining: *{ch_data['name']}*\n\n"
                f"Please select a subscription plan below:",
                reply_markup=markup, 
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                message.chat.id, 
                "👋 *Welcome!*\n\n"
                "There are no active paid channels right now.\n"
                "Please contact the admin for more information.",
                parse_mode="Markdown"
            )

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_channels(message):
    markup = InlineKeyboardMarkup()
    cursor = channels_col.find({"admin_id": ADMIN_ID})
    count = 0
    for ch in cursor:
        markup.add(InlineKeyboardButton(f"📢 {ch['name']}", callback_data=f"manage_{ch['channel_id']}"))
        count += 1
    
    markup.add(InlineKeyboardButton("➕ Add New Channel", callback_data="add_new"))
    
    if count == 0:
        bot.send_message(ADMIN_ID, "No channels found. Click below to add one.", reply_markup=markup)
    else:
        bot.send_message(ADMIN_ID, "Your Managed Channels:", reply_markup=markup)

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_channel_start(message):
    msg = bot.send_message(
        ADMIN_ID, 
        "📌 *Step 1:* Make sure this bot is an **Administrator** in your target channel "
        "(with permissions: Invite Users via Link + Ban Users).\n\n"
        "📌 *Step 2:* FORWARD any message from that channel to here."
    )
    bot.register_next_step_handler(msg, get_plans)

@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "FORWARD any message from your target channel here.")
    bot.register_next_step_handler(msg, get_plans)

def get_plans(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title or "Unnamed Channel"
        msg = bot.send_message(
            ADMIN_ID, 
            f"✅ Channel Detected: *{ch_name}*\n\n"
            "Enter subscription plans in this format:\n"
            "`Minutes:Stars, Minutes:Stars`\n\n"
            "Examples:\n"
            "• `60:5` → 1 Hour for 5 Stars\n"
            "• `1440:20` → 1 Day for 20 Stars\n"
            "• `10080:50` → 7 Days for 50 Stars\n\n"
            "💡 Tip: Keep prices reasonable (check current Star value ~₹1.2-1.7 per Star)",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, finalize_channel, ch_id, ch_name)
    else:
        bot.send_message(ADMIN_ID, "❌ Error: Message was not forwarded from a channel. Use /add again.")

def finalize_channel(message, ch_id, ch_name):
    try:
        raw_plans = message.text.split(',')
        plans_dict = {}
        for p in raw_plans:
            t, pr = p.strip().split(':')
            plans_dict[str(int(t))] = int(pr)  # Store minutes as str key, stars as int
        
        channels_col.update_one(
            {"channel_id": ch_id}, 
            {"$set": {"name": ch_name, "plans": plans_dict, "admin_id": ADMIN_ID}}, 
            upsert=True
        )
        bot_username = bot.get_me().username
        invite_link = f"https://t.me/{bot_username}?start={ch_id}"
        
        bot.send_message(
            ADMIN_ID, 
            f"✅ *Channel Setup Successful!*\n\n"
            f"Channel: {ch_name}\n"
            f"Invite users with this link:\n`{invite_link}`\n\n"
            "Users will see your plans and pay with Telegram Stars automatically.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"finalize_channel error: {e}")
        bot.send_message(ADMIN_ID, "❌ Invalid format. Use `Minutes:Stars, Minutes:Stars`. Example: `1440:20, 10080:50`")

# --- USER: STARS PAYMENT FLOW (REPLACED UPI) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def select_plan(call):
    """User clicked a plan button → Send Telegram Stars Invoice (automatic payment)"""
    try:
        _, ch_id_str, mins_str = call.data.split('_')
        ch_id = int(ch_id_str)
        mins = int(mins_str)
        
        ch_data = channels_col.find_one({"channel_id": ch_id})
        if not ch_data:
            bot.answer_callback_query(call.id, "Channel not found.")
            return
        
        stars_price = ch_data['plans'].get(mins_str) or ch_data['plans'].get(str(mins))
        if not stars_price:
            bot.answer_callback_query(call.id, "Plan not available.")
            return
        
        # Create nice title/description
        if mins < 60:
            time_label = f"{mins} Minutes"
        elif mins < 1440:
            time_label = f"{mins // 60} Hours"
        else:
            time_label = f"{mins // 1440} Days"
        
        title = f"{time_label} Access to {ch_data['name']}"
        description = (
            f"Get temporary access to the channel for {time_label}.\n"
            f"Access will be automatically revoked after expiry.\n"
            f"Pay securely with Telegram Stars."
        )
        
        # Payload to identify the purchase later
        payload = f"sub_{ch_id}_{mins}_{call.from_user.id}"
        
        prices = [LabeledPrice(label=f"{time_label} Access", amount=int(stars_price))]
        
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title=title,
            description=description,
            invoice_payload=payload,
            provider_token="",           # IMPORTANT: Empty for Telegram Stars
            currency="XTR",              # Telegram Stars currency
            prices=prices,
            # Optional: photo_url if you have a nice image
        )
        
        bot.answer_callback_query(call.id, "Opening payment...")
        
    except Exception as e:
        logger.error(f"select_plan error: {e}")
        bot.answer_callback_query(call.id, "Error creating invoice. Try again.")

# --- TELEGRAM STARS PAYMENT HANDLERS (NEW) ---

@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout_query_handler(pre_checkout_query):
    """Always approve pre-checkout for digital access (no physical goods)"""
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        logger.info(f"Pre-checkout approved for user {pre_checkout_query.from_user.id}")
    except Exception as e:
        logger.error(f"pre_checkout error: {e}")

@bot.message_handler(content_types=['successful_payment'])
def successful_payment_handler(message):
    """Payment successful → Automatically grant access (no admin approval needed!)"""
    try:
        payment = message.successful_payment
        payload = payment.invoice_payload
        
        # Parse payload: sub_CHANNELID_MINUTES_USERID
        parts = payload.split('_')
        if len(parts) != 4 or parts[0] != "sub":
            logger.warning(f"Invalid payload: {payload}")
            return
        
        ch_id = int(parts[1])
        mins = int(parts[2])
        user_id = int(parts[3])
        
        # Security: Only the payer gets access
        if user_id != message.from_user.id:
            logger.warning("Payment user mismatch")
            return
        
        ch_data = channels_col.find_one({"channel_id": ch_id})
        if not ch_data:
            bot.send_message(user_id, "❌ Channel not found. Contact support.")
            return
        
        # Calculate expiry
        expiry_datetime = datetime.now() + timedelta(minutes=mins)
        expiry_ts = expiry_datetime.timestamp()
        
        # Create single-use, time-limited invite link
        try:
            invite_link = bot.create_chat_invite_link(
                chat_id=ch_id,
                member_limit=1,
                expire_date=int(expiry_ts)
            )
        except Exception as link_err:
            logger.error(f"Invite link creation failed: {link_err}")
            bot.send_message(user_id, "✅ Payment received! But failed to create invite link. Contact admin immediately.")
            return
        
        # Save subscription to DB
        users_col.update_one(
            {"user_id": user_id, "channel_id": ch_id},
            {"$set": {
                "expiry": expiry_ts,
                "plan_minutes": mins,
                "paid_stars": payment.total_amount
            }},
            upsert=True
        )
        
        # Send beautiful success message with link
        time_label = f"{mins} minutes" if mins < 60 else f"{mins // 60} hours" if mins < 1440 else f"{mins // 1440} days"
        
        success_text = (
            f"🎉 *Payment Successful!*\n\n"
            f"✅ You now have *{time_label}* access to *{ch_data['name']}*.\n\n"
            f"🔗 *Your Personal Invite Link:*\n{invite_link.invite_link}\n\n"
            f"⏰ *Expires:* {expiry_datetime.strftime('%d %b %Y, %H:%M UTC')}\n\n"
            f"⚠️ *Important:*\n"
            f"• This link works only once\n"
            f"• You will be automatically removed after expiry\n"
            f"• Come back to this bot to renew anytime\n\n"
            f"Thank you for your support! ⭐"
        )
        
        bot.send_message(user_id, success_text, parse_mode="Markdown")
        
        logger.info(f"Access granted to user {user_id} for channel {ch_id} ({mins} mins)")
        
    except Exception as e:
        logger.error(f"successful_payment_handler error: {e}")
        try:
            bot.send_message(message.from_user.id, "❌ There was an error processing your payment. Please contact support.")
        except:
            pass

# --- CHANNEL MANAGEMENT (Unchanged) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_'))
def manage_ch(call):
    try:
        ch_id = int(call.data.split('_')[1])
        ch_data = channels_col.find_one({"channel_id": ch_id})
        bot_username = bot.get_me().username
        link = f"https://t.me/{bot_username}?start={ch_id}"
        
        bot.edit_message_text(
            f"📢 *Settings for: {ch_data['name']}*\n\n"
            f"🔗 User Invite Link:\n`{link}`\n\n"
            f"To change prices or plans, use /add and forward a message from this channel again.\n\n"
            f"Current Plans: {ch_data.get('plans', {})}",
            call.message.chat.id, 
            call.message.message_id, 
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"manage_ch error: {e}")

# --- AUTOMATIC EXPIRY & KICK (Unchanged, works perfectly) ---

def kick_expired_users():
    now = datetime.now().timestamp()
    expired_users = users_col.find({"expiry": {"$lte": now}})
    bot_username = bot.get_me().username

    for user in expired_users:
        try:
            # Kick user (ban + unban = kick)
            bot.ban_chat_member(user['channel_id'], user['user_id'])
            bot.unban_chat_member(user['channel_id'], user['user_id'])
            
            rejoin_url = f"https://t.me/{bot_username}?start={user['channel_id']}"
            markup = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔄 Renew / Re-join", url=rejoin_url)
            )
            
            bot.send_message(
                user['user_id'], 
                "⚠️ *Your subscription has expired.*\n\n"
                "To join again or renew, click the button below:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            users_col.delete_one({"_id": user['_id']})
            logger.info(f"Kicked expired user {user['user_id']} from channel {user['channel_id']}")
        except Exception as e:
            logger.error(f"Kick error for user {user.get('user_id')}: {e}")

# --- STARTUP ---
if __name__ == '__main__':
    keep_alive()
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_users, 'interval', minutes=1)
    scheduler.start()
    
    bot.remove_webhook()
    logger.info("🚀 Telegram Stars Subscription Bot started successfully!")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
