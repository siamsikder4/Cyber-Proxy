import os
import io
import json
import asyncio
import logging
from datetime import datetime
from aiohttp import web
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import firebase_admin
from firebase_admin import credentials, firestore
import openpyxl

# --- কনফিগারেশন ---
BOT_TOKEN = "8868386011:AAEulcSqsAr2DxvBLRdMNANzDfCak5MN64Q"
SUPER_ADMIN_ID = 8271633124

# স্থায়ীভাবে লোকাল স্টোরেজে সংরক্ষণের ফাইল পাথ
LOCAL_STORE_FILE = "persistent_config.json"
FIREBASE_KEY_PATH = "serviceAccountKey.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

db = None

# --- ফায়ারবেস অটো লোডার (পরিবেশ বা স্থায়ী ফাইল থেকে) ---
def load_firebase():
    global db
    if db:
        return True

    cred_dict = None

    # ১. এনভায়রনমেন্ট ভেরিয়েবল চেক
    env_creds = os.environ.get("FIREBASE_CREDENTIALS")
    if env_creds:
        try:
            cred_dict = json.loads(env_creds)
        except Exception as e:
            logging.error(f"Failed to parse FIREBASE_CREDENTIALS: {e}")

    # ২. স্থায়ী সংরক্ষিত কনফিগ ফাইল চেক
    if not cred_dict and os.path.exists(LOCAL_STORE_FILE):
        try:
            with open(LOCAL_STORE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cred_dict = saved.get("firebase_credentials")
        except Exception as e:
            logging.error(f"Failed to read {LOCAL_STORE_FILE}: {e}")

    # ৩. সরাসরি ফাইল চেক
    if not cred_dict and os.path.exists(FIREBASE_KEY_PATH):
        try:
            with open(FIREBASE_KEY_PATH, "r", encoding="utf-8") as f:
                cred_dict = json.load(f)
        except Exception as e:
            logging.error(f"Failed to read {FIREBASE_KEY_PATH}: {e}")

    # ফায়ারবেস ইনিশিয়ালাইজেশন
    if cred_dict:
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            init_settings()
            logging.info("Firebase authenticated successfully!")
            return True
        except Exception as e:
            logging.error(f"Firebase connection failed: {e}")
            db = None
            return False

    return False

def init_settings():
    global db
    if not db:
        return
    try:
        set_ref = db.collection("settings").document("payments")
        if not set_ref.get().exists:
            set_ref.set({
                "bkash": "01XXXXXXXXX",
                "nagad": "01XXXXXXXXX",
                "rocket": "01XXXXXXXXX",
                "binance": "12345678",
                "dollar_rate": 125.0
            })

        misc_ref = db.collection("settings").document("misc")
        if not misc_ref.get().exists:
            misc_ref.set({
                "support_link": "https://t.me/your_admin",
                "bot_display_name": "Your Proxy",
                "force_channel": ""
            })
    except Exception as e:
        logging.error(f"Settings init error: {e}")

# Conversation States
(
    UPLOAD_FIREBASE_JSON,
    UPLOAD_STOCK,
    FIND_USER,
    USER_ACTION_AMOUNT,
    USER_SEND_MSG,
    EDIT_PAYMENT_VALUE,
    DEPOSIT_METHOD,
    DEPOSIT_AMOUNT,
    DEPOSIT_PROOF,
    ADD_PROD_CAT,
    ADD_PROD_NAME,
    ADD_PROD_PRICE,
    CHANGE_PRICE_SELECT,
    CHANGE_PRICE_VAL,
    BROADCAST_RECEIVE,
    ADD_VOUCHER_CODE,
    ADD_VOUCHER_BAL,
    REDEEM_VOUCHER,
    ADD_ADMIN_ID,
    SETUP_SUPPORT,
    RESELLER_UID
) = range(1, 22)

def is_admin_sync(user_id: int) -> bool:
    if int(user_id) == int(SUPER_ADMIN_ID):
        return True
    if db:
        try:
            return db.collection("admins").document(str(user_id)).get().exists
        except Exception:
            return False
    return False

# --- কীবোর্ড মেনু ---
def get_user_menu(is_admin=False):
    kb = [
        [KeyboardButton("🛍️ Buy Product")],
        [KeyboardButton("👤 My Profile"), KeyboardButton("💳 Deposit")],
        [KeyboardButton("🏷️ Get Code"), KeyboardButton("💬 Support")],
    ]
    if is_admin:
        kb.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_admin_menu():
    kb = [
        [KeyboardButton("💼 Product Management"), KeyboardButton("📦 Add Stock")],
        [KeyboardButton("📊 Live Stock"), KeyboardButton("👥 User Management")],
        [KeyboardButton("🔔 Deposit Requests"), KeyboardButton("📜 Deposit History")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("🏷️ Voucher Management")],
        [KeyboardButton("🛠️ Support Setup"), KeyboardButton("💳 Payment Settings")],
        [KeyboardButton("🔑 Admin Management"), KeyboardButton("🤝 Reseller Management")],
        [KeyboardButton("⚙️ Setup Firebase"), KeyboardButton("🔙 User Menu")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# --- START COMMAND ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = is_admin_sync(user.id)

    if db:
        try:
            user_ref = db.collection("users").document(str(user.id))
            doc = user_ref.get()
            if not doc.exists:
                user_ref.set({
                    "name": user.full_name or "User",
                    "username": user.username or "None",
                    "balance": 0.0,
                    "orders": 0,
                    "joined": datetime.now().strftime("%Y-%m-%d"),
                    "is_banned": False,
                    "is_reseller": False
                })
            else:
                user_ref.update({
                    "name": user.full_name or "User",
                    "username": user.username or "None"
                })
        except Exception as e:
            logging.error(f"User registration error: {e}")

    if not db and is_admin:
        msg = (
            "⚠️ *Firebase Not Configured!*\n\n"
            "Open *👑 Admin Panel* ❯ *⚙️ Setup Firebase* to upload your `serviceAccountKey.json` once.\n"
            "It will stay saved permanently."
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_user_menu(is_admin=True))
        return

    welcome_msg = (
        f"👋 *Welcome, {user.first_name}!*\n\n"
        f"Select an option from the menu below to start purchasing proxies, accounts, and tools."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_user_menu(is_admin))

# --- MY PROFILE ---
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ System offline. Please try again later.")
        return
    user_id = str(update.effective_user.id)
    data = db.collection("users").document(user_id).get().to_dict() or {}
    balance = data.get("balance", 0.0)
    usd = balance / 125.0
    joined = data.get("joined", "2026-10-08")

    card = (
        "👤 *My Profile*\n\n"
        f"👤 Name     : {data.get('name', 'N/A')}\n"
        f"🆔 User ID  : `{user_id}`\n"
        f"💲 Balance  : *{balance:.2f} BDT* / {usd:.4f} USDT\n"
        f"⏳ Joined   : {joined}\n"
        f"───────────────────────────"
    )
    kb = [[InlineKeyboardButton("🍇 Referral", callback_data="user_referral")]]
    await update.message.reply_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# --- SUPPORT ---
async def user_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = "https://t.me"
    if db:
        misc = db.collection("settings").document("misc").get().to_dict() or {}
        link = misc.get("support_link", link)

    msg = (
        "🗣️ *Our Support Team*\n\n"
        "For any issues or inquiries, click the button below to contact support directly."
    )
    kb = [[InlineKeyboardButton("🗣️ Contact Admin", url=link)]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# --- স্থায়ী ফায়ারবেস আপলোড এবং সংরক্ষণ ---
async def ask_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return ConversationHandler.END

    msg = (
        "📁 *Permanent Firebase Setup*\n\n"
        "আপনার `serviceAccountKey.json` ফাইলটি পাঠান।\n"
        "এটি সেভ করার পর আপনাকে আর কোড আপডেট করলেও পুনরায় দিতে হবে না।"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return UPLOAD_FIREBASE_JSON

async def save_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".json"):
        await update.message.reply_text("❌ অনুগ্রহ করে সঠিক `.json` ফাইল পাঠান।")
        return UPLOAD_FIREBASE_JSON

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    try:
        data_dict = json.loads(file_bytes.decode("utf-8"))

        # ১. লোকাল ফাইল হিসেবে সেভ
        with open(FIREBASE_KEY_PATH, "w", encoding="utf-8") as f:
            json.dump(data_dict, f)

        # ২. স্থায়ী কনফিগ ফাইলে এনকোড করে রাখা
        with open(LOCAL_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"firebase_credentials": data_dict}, f)

        # ৩. কারেন্ট সেশনে রিলোড
        if load_firebase():
            # Render-এর জন্য এনভায়রনমেন্ট ভ্যালু টেক্সট তৈরি করে দেওয়া
            compact_json = json.dumps(data_dict)
            await update.message.reply_text(
                "✅ *Firebase সফলভাবে যুক্ত ও সক্রিয় হয়েছে!*\n\n"
                "📌 *স্থায়ী ব্যাকআপ পরামর্শ (Render Users):*\n"
                "Render ড্যাশবোর্ডের Environment-এ `FIREBASE_CREDENTIALS` নামে ভ্যারিয়েবল যোগ করে নিচের মানটি দিলে গিটহাব কোড পুরোপুরি পাল্টে গেলেও এটি কখনো মুছবে না:\n\n"
                f"`{compact_json[:100]}... (Saved Locally)`",
                parse_mode="Markdown",
                reply_markup=get_admin_menu()
            )
        else:
            await update.message.reply_text("❌ ফাইলটি পাওয়া গেছে তবে Firebase অথেনটিকেশন ব্যর্থ হয়েছে।")
    except Exception as e:
        await update.message.reply_text(f"❌ JSON পার্সিং এরর: `{e}`", parse_mode="Markdown")

    return ConversationHandler.END

# --- DEPOSIT SYSTEM WITH SCREENSHOT & TRXID ---
async def user_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ ডাটাবেজ অফলাইনে রয়েছে।")
        return ConversationHandler.END

    settings = db.collection("settings").document("payments").get().to_dict() or {}
    kb = [
        [InlineKeyboardButton("💳 bKash", callback_data="paymeth_bkash"), InlineKeyboardButton("💳 Nagad", callback_data="paymeth_nagad")],
        [InlineKeyboardButton("💳 Rocket", callback_data="paymeth_rocket"), InlineKeyboardButton("💳 Binance", callback_data="paymeth_binance")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    msg = "💳 *Deposit*\n\nপেমেন্ট মেথড বেছে নিন:"
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_method_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("paymeth_", "")
    context.user_data["dep_method"] = method

    settings = db.collection("settings").document("payments").get().to_dict() or {}
    acc_num = settings.get(method, "Not Set")

    msg = (
        f"💳 *Deposit via {method.upper()}*\n\n"
        f"টাকা পাঠানোর নাম্বার / Pay ID: `{acc_num}`\n\n"
        f"আপনি কত টাকা পাঠিয়েছেন তা লিখুন (in BDT):"
    )
    await query.edit_message_text(msg, parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        if amt <= 0:
            raise ValueError()
        context.user_data["dep_amount"] = amt
    except Exception:
        await update.message.reply_text("❌ অনুগ্রহ করে সঠিক টাকার পরিমাণ লিখুন (যেমন: 100):")
        return DEPOSIT_AMOUNT

    await update.message.reply_text(
        "📸 এবার পেমেন্টের *Transaction ID (TrxID)* লিখে পাঠান অথবা পেমেন্ট স্লিপের *Screenshot (SS)* ছবি আকারে পাঠান:",
        parse_mode="Markdown"
    )
    return DEPOSIT_PROOF

async def deposit_proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    amt = context.user_data.get("dep_amount")
    method = context.user_data.get("dep_method")
    photo_file_id = None
    trx_text = "N/A"

    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        trx_text = update.message.caption or "Screenshot Attached"
    elif update.message.text:
        trx_text = update.message.text.strip()

    if not db:
        await update.message.reply_text("⚠️ ডাটাবেজ অফলাইন।")
        return ConversationHandler.END

    req_ref = db.collection("deposit_requests").add({
        "user_id": uid,
        "amount": amt,
        "method": method,
        "proof": trx_text,
        "photo_id": photo_file_id,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    req_id = req_ref[1].id

    kb = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{req_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{req_id}")]
    ]

    admin_caption = (
        f"🔔 *NEW DEPOSIT REQUEST*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• User ID : `{uid}`\n"
        f"• Amount  : *{amt:.2f} BDT*\n"
        f"• Method  : {method.upper()}\n"
        f"• Proof   : `{trx_text}`"
    )

    try:
        if photo_file_id:
            await context.bot.send_photo(
                chat_id=SUPER_ADMIN_ID,
                photo=photo_file_id,
                caption=admin_caption,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await context.bot.send_message(
                chat_id=SUPER_ADMIN_ID,
                text=admin_caption,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

    await update.message.reply_text(
        "✅ *ডিপোজিট রিকোয়েস্ট সফলভাবে জমা হয়েছে!*\nঅ্যাডমিন যাচাই করার পর আপনার ব্যালেন্সে যোগ হবে।",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# --- BUYING FLOW & QUANTITY COUNTER ---
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ শপ বর্তমানে অফলাইন।")
        return

    # অ্যাডমিন যোগ করার পরেই কেবল ক্যাটাগরিগুলো ডাইনামিকালি লোড হবে
    prods = db.collection("products").get()
    cats = sorted(list(set(p.to_dict().get("cat") for p in prods if p.to_dict().get("cat"))))

    if not cats:
        await update.message.reply_text("🛍️ *দোকানটি বর্তমানে খালি!*\nকোনো প্রোডাক্ট এখনো যোগ করা হয়নি।", parse_mode="Markdown")
        return

    buttons = []
    row = []
    for c in cats:
        icon = "🌐" if "Proxy" in c else "🛡️" if "VPN" in c else "✉️"
        row.append(InlineKeyboardButton(f"{icon} {c}", callback_data=f"buycat_{c}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")])

    await update.message.reply_text("🛒 *Buy Products*\n\nSelect a category:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def handle_buy_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("buycat_", "")

    prods = db.collection("products").where("cat", "==", category).get()
    if not prods:
        await query.edit_message_text(f"❌ No products under *{category}*.", parse_mode="Markdown")
        return

    buttons = []
    for p in prods:
        p_data = p.to_dict()
        buttons.append([InlineKeyboardButton(f"🔹 {p_data['name']} ❯ {p_data['price']:.0f} BDT", callback_data=f"selpkg_{p.id}")])
    buttons.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="back_to_cats")])

    await query.edit_message_text(f"🛒 *Category: {category}*\n\nSelect a product:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

def build_purchase_summary_kb(qty: int, prod_id: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"qty_dec_{prod_id}_{qty}"),
            InlineKeyboardButton(f"{qty}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"qty_inc_{prod_id}_{qty}")
        ],
        [InlineKeyboardButton("🔢 Enter quantity", callback_data=f"qty_manual_{prod_id}")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_to_cats"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")
        ],
        [InlineKeyboardButton("✅ Confirm", callback_data=f"buy_confirm_{prod_id}_{qty}")]
    ])

async def show_purchase_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = query.data.replace("selpkg_", "")

    prod = db.collection("products").document(prod_id).get().to_dict()
    if not prod:
        await query.edit_message_text("❌ Product not found.")
        return

    qty = 1
    unit_price = prod.get("price", 0.0)
    total_price = unit_price * qty

    summary_text = (
        "🧾 *PURCHASE SUMMARY*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 *Category:* {prod.get('cat')}\n"
        f"🔹 *Package:* {prod.get('name')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Quantity:* {qty}\n"
        f"💲 *Rate:* {unit_price:.2f} BDT\n"
        f"🛒 *Total Price:* {total_price:.2f} BDT"
    )
    await query.edit_message_text(summary_text, reply_markup=build_purchase_summary_kb(qty, prod_id), parse_mode="Markdown")

async def update_quantity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]
    prod_id = parts[2]
    qty = int(parts[3])

    if action == "inc":
        qty += 1
    elif action == "dec" and qty > 1:
        qty -= 1

    prod = db.collection("products").document(prod_id).get().to_dict()
    unit_price = prod.get("price", 0.0)
    total_price = unit_price * qty

    summary_text = (
        "🧾 *PURCHASE SUMMARY*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 *Category:* {prod.get('cat')}\n"
        f"🔹 *Package:* {prod.get('name')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Quantity:* {qty}\n"
        f"💲 *Rate:* {unit_price:.2f} BDT\n"
        f"🛒 *Total Price:* {total_price:.2f} BDT"
    )
    await query.edit_message_text(summary_text, reply_markup=build_purchase_summary_kb(qty, prod_id), parse_mode="Markdown")

async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    _, _, prod_id, qty_str = query.data.split("_")
    qty = int(qty_str)

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get().to_dict() or {}
    if user_doc.get("is_banned"):
        await query.answer("🚫 Account banned.", show_alert=True)
        return

    prod_ref = db.collection("products").document(prod_id)
    prod_doc = prod_ref.get().to_dict()
    if not prod_doc:
        await query.answer("❌ Product not found.", show_alert=True)
        return

    unit_price = prod_doc["reseller"] if user_doc.get("is_reseller") else prod_doc["price"]
    total_cost = unit_price * qty

    if user_doc.get("balance", 0.0) < total_cost:
        await query.answer("❌ Insufficient balance! Please deposit first.", show_alert=True)
        return

    stocks_ref = prod_ref.collection("stocks").limit(qty).get()
    if len(stocks_ref) < qty:
        await query.answer(f"❌ Not enough stock! Available: {len(stocks_ref)}", show_alert=True)
        return

    delivered_items = []
    batch = db.batch()
    for s in stocks_ref:
        delivered_items.append(s.to_dict().get("data", ""))
        batch.delete(s.reference)
    batch.commit()

    remaining_bal = user_doc.get("balance", 0.0) - total_cost
    user_ref.update({
        "balance": remaining_bal,
        "orders": firestore.Increment(qty)
    })

    credentials_block = "\n".join(f"`{item}`" for item in delivered_items)

    receipt = (
        f"🎉 *{prod_doc.get('cat', 'Product')} purchase successful!* ✅\n\n"
        f"🔹 *Product:* {prod_doc['name']}\n"
        f"💲 *Remaining Balance:* {remaining_bal:.2f} BDT\n\n"
        f"⬇️ *Your Credentials:*\n\n"
        f"{credentials_block}\n\n"
        f"🔥 _Thank you for shopping with us!_"
    )
    await query.edit_message_text(receipt, parse_mode="Markdown")

# --- BROADCAST SYSTEM WITH VOICE SUPPORT ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📢 *Send Broadcast Material:*\n\n"
        "You can send:\n"
        "• 📝 *Text Message*\n"
        "• 🎙️ *Voice Message*\n"
        "• 📸 *Photo with caption*\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown"
    )
    return BROADCAST_RECEIVE

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        return ConversationHandler.END

    users = db.collection("users").get()
    status_msg = await update.message.reply_text("🚀 Broadcasting to all users...")
    success, failed = 0, 0

    for u in users:
        uid = int(u.id)
        try:
            if update.message.voice:
                await context.bot.send_voice(chat_id=uid, voice=update.message.voice.file_id, caption=update.message.caption)
            elif update.message.photo:
                await context.bot.send_photo(chat_id=uid, photo=update.message.photo[-1].file_id, caption=update.message.caption)
            elif update.message.text:
                await context.bot.send_message(chat_id=uid, text=update.message.text)
            success += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"📢 *Broadcast Completed!*\n\n"
        f"✅ Delivered : `{success}`\n"
        f"❌ Failed    : `{failed}`",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# --- ADMIN PANEL & LIVE STOCK ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("👑 *Admin Control Panel*", reply_markup=get_admin_menu(), parse_mode="Markdown")

async def live_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return
    prods = db.collection("products").get()
    if not prods:
        await update.message.reply_text("🌐 *Live Stock*\n\nNo products added yet.", parse_mode="Markdown")
        return

    msg = "🌐 *Live Stock Feed*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for p in prods:
        d = p.to_dict()
        count = len(p.reference.collection("stocks").get())
        msg += f"📦 *{d['name']}* | Price: `{d['price']:.0f}৳`\n• Category: {d.get('cat')} | Stock: `{count}`\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- STOCK UPLOAD (TXT / XLSX) ---
async def add_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return

    prods = db.collection("products").get()
    if not prods:
        await update.message.reply_text("❌ Please add a product first before uploading stock.")
        return

    buttons = [[InlineKeyboardButton(p.to_dict()["name"], callback_data=f"upstock_{p.id}")] for p in prods]
    await update.message.reply_text("🗂️ Select product to add stock:", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_prepare_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = query.data.replace("upstock_", "")
    context.user_data["upload_prod_id"] = prod_id

    prod_name = db.collection("products").document(prod_id).get().to_dict().get("name")
    instruction = (
        f"🗂️ *Upload Stock for:* `{prod_name}`\n\n"
        f"Send an *Excel (.xlsx)* or *Text (.txt)* file:\n\n"
        f"📌 *Supported Formats:*\n"
        f"✏️ *TXT File:* `Host:Port:Username:Password`\n"
        f"🧪 *Excel File:* Col A=Host, B=Port, C=User, D=Pass"
    )
    await query.edit_message_text(instruction, parse_mode="Markdown")
    return UPLOAD_STOCK

async def process_stock_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    prod_id = context.user_data.get("upload_prod_id")
    if not prod_id or not db:
        await update.message.reply_text("❌ Error processing upload.")
        return ConversationHandler.END

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    entries = []

    if doc.file_name.endswith(".txt"):
        for line in file_bytes.decode("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line:
                entries.append(line)
    elif doc.file_name.endswith(".xlsx"):
        wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active
        for row in sheet.iter_rows(values_only=True):
            if any(row):
                line = ":".join(str(c).strip() for c in row[:4] if c is not None)
                entries.append(line)

    if entries:
        prod_ref = db.collection("products").document(prod_id)
        batch = db.batch()
        for item in entries:
            batch.set(prod_ref.collection("stocks").document(), {"data": item})
        batch.commit()
        await update.message.reply_text(f"✅ Loaded `{len(entries)}` items into stock!", parse_mode="Markdown", reply_markup=get_admin_menu())
    else:
        await update.message.reply_text("❌ No items parsed from file.")
    return ConversationHandler.END

# --- PRODUCT MANAGEMENT ---
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    kb = [
        [InlineKeyboardButton("👑 Add New Product", callback_data="prodman_add")],
        [InlineKeyboardButton("❌ Delete Product", callback_data="prodman_delprod")],
        [InlineKeyboardButton("🧨 Clear All Stock", callback_data="prodman_delstock")],
    ]
    await update.message.reply_text("⚙️ *Product Management Console*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_prodman_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("prodman_", "")

    if act == "add":
        await query.edit_message_text("Type the Category name (e.g. Proxy, VPN, Mail):")
        return ADD_PROD_CAT
    elif act == "delprod":
        prods = db.collection("products").get()
        kb = [[InlineKeyboardButton(f"❌ {p.to_dict()['name']}", callback_data=f"delp_{p.id}")] for p in prods]
        await query.edit_message_text("Select product to delete:", reply_markup=InlineKeyboardMarkup(kb))
    elif act == "delstock":
        prods = db.collection("products").get()
        kb = [[InlineKeyboardButton(f"🧨 Empty {p.to_dict()['name']}", callback_data=f"clearstock_{p.id}")] for p in prods]
        await query.edit_message_text("Select product to wipe stock:", reply_markup=InlineKeyboardMarkup(kb))

async def save_add_prod_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cat"] = update.message.text.strip()
    await update.message.reply_text("Enter Product Name (e.g. 711 PROXY 1 GB):")
    return ADD_PROD_NAME

async def save_add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("Enter Regular & Reseller Price (e.g. `70 65`):", parse_mode="Markdown")
    return ADD_PROD_PRICE

async def save_add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ Please enter valid numbers (e.g. `70 65`):")
        return ADD_PROD_PRICE

    db.collection("products").add({
        "cat": context.user_data.get("new_cat"),
        "name": context.user_data.get("new_name"),
        "price": price,
        "reseller": reseller
    })
    await update.message.reply_text("✅ Product successfully created and listed!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- DEPOSIT APPROVAL / REJECTION ---
async def show_deposit_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    reqs = db.collection("deposit_requests").where("status", "==", "pending").get()
    if not reqs:
        await update.message.reply_text("✅ No pending deposits.")
        return

    for r in reqs:
        d = r.to_dict()
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{r.id}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{r.id}")]]
        card = (
            f"🔔 *PENDING DEPOSIT*\n"
            f"• User ID : `{d['user_id']}`\n"
            f"• Amount  : *{d['amount']:.2f} BDT*\n"
            f"• Method  : {d['method'].upper()}\n"
            f"• Proof   : `{d.get('proof', 'N/A')}`"
        )
        if d.get("photo_id"):
            await context.bot.send_photo(chat_id=update.effective_user.id, photo=d["photo_id"], caption=card, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(card, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def handle_deposit_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act, req_id = query.data.split("_")

    ref = db.collection("deposit_requests").document(req_id)
    doc = ref.get()
    if not doc.exists:
        return

    data = doc.to_dict()
    if data["status"] != "pending":
        await query.edit_message_caption(caption="⚠️ Already processed.") if query.message.photo else await query.edit_message_text("⚠️ Already processed.")
        return

    if act == "depapp":
        ref.update({"status": "approved"})
        db.collection("users").document(data["user_id"]).update({"balance": firestore.Increment(data["amount"])})
        try:
            await context.bot.send_message(
                chat_id=int(data["user_id"]),
                text=f"✅ *Deposit Approved!*\n*{data['amount']:.2f} BDT* has been credited to your balance.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        msg = f"✅ Approved: {data['amount']:.2f} BDT for `{data['user_id']}`"
    else:
        ref.update({"status": "rejected"})
        try:
            await context.bot.send_message(chat_id=int(data["user_id"]), text=f"❌ Deposit request of {data['amount']} BDT was rejected.")
        except Exception:
            pass
        msg = f"❌ Rejected deposit for `{data['user_id']}`"

    if query.message.photo:
        await query.edit_message_caption(caption=msg)
    else:
        await query.edit_message_text(msg)

# --- CANCEL & NOOP ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=get_user_menu(is_admin_sync(update.effective_user.id)))
    return ConversationHandler.END

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Canceled.")

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# --- RENDER WEB SERVICE PORT LISTENER ---
async def health_check(request):
    return web.Response(text="Bot is running fine on Render Web Service!")

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Render Web Service listener active on port {port}...")

# --- MAIN RUNNER ---
async def run_bot():
    load_firebase()
    app = Application.builder().token(BOT_TOKEN).build()

    # স্থায়ী Firebase Setup হ্যান্ডলার
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⚙️ Setup Firebase$"), ask_firebase_json)],
        states={UPLOAD_FIREBASE_JSON: [MessageHandler(filters.Document.ALL, save_firebase_json)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Add Stock
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_prepare_upload, pattern=r"^upstock_")],
        states={UPLOAD_STOCK: [MessageHandler(filters.Document.ALL, process_stock_file)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Deposit with Text / Photo (SS)
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💳 Deposit$"), user_deposit_start)],
        states={
            DEPOSIT_AMOUNT: [
                CallbackQueryHandler(deposit_method_picked, pattern=r"^paymeth_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount_received)
            ],
            DEPOSIT_PROOF: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, deposit_proof_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Add Product
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_add$")],
        states={
            ADD_PROD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_cat)],
            ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_name)],
            ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Broadcast (Text / Voice / Photo)
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast$"), start_broadcast)],
        states={BROADCAST_RECEIVE: [MessageHandler((filters.TEXT | filters.VOICE | filters.PHOTO) & ~filters.COMMAND, execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Navigation Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ Buy Product$"), buy_products_menu))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^💬 Support$"), user_support))
    app.add_handler(MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^💼 Product Management$"), product_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^📊 Live Stock$"), live_stock))
    app.add_handler(MessageHandler(filters.Regex("^📦 Add Stock$"), add_stock_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔔 Deposit Requests$"), show_deposit_requests))
    app.add_handler(MessageHandler(filters.Regex("^(🔙 User Menu|✅ User Menu)$"), start))

    # Inline Callbacks
    app.add_handler(CallbackQueryHandler(buy_products_menu, pattern=r"^back_to_cats$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^cancel_action$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(handle_buy_cat, pattern=r"^buycat_"))
    app.add_handler(CallbackQueryHandler(show_purchase_summary, pattern=r"^selpkg_"))
    app.add_handler(CallbackQueryHandler(update_quantity_callback, pattern=r"^qty_(inc|dec)_"))
    app.add_handler(CallbackQueryHandler(confirm_purchase, pattern=r"^buy_confirm_"))
    app.add_handler(CallbackQueryHandler(handle_deposit_decide, pattern=r"^dep(app|rej)_"))

    # Render Web Server পোর্ট বাইন্ডিং
    await start_web_server()

    async with app:
        await app.start()
        await app.updater.start_polling()
        logging.info("Bot is polling and Web Service is running...")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(run_bot())