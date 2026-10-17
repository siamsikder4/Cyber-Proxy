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

# --- CONFIGURATION ---
BOT_TOKEN = "8868386011:AAEulcSqsAr2DxvBLRdMNANzDfCak5MN64Q"
SUPER_ADMIN_ID = 8271633124

PERSISTENT_FILE = "persistent_config.json"
FIREBASE_KEY_PATH = "serviceAccountKey.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

db = None

# --- FIREBASE CONNECTOR (স্থায়ী মেমরি ও ফাইল ব্যাকআপ) ---
def load_firebase():
    global db
    if db:
        return True

    cred_dict = None

    # ১. এনভায়রনমেন্ট ভেরিয়েবল
    env_creds = os.environ.get("FIREBASE_CREDENTIALS")
    if env_creds:
        try:
            cred_dict = json.loads(env_creds)
        except Exception as e:
            logging.error(f"Failed to parse FIREBASE_CREDENTIALS: {e}")

    # ২. পার্মানেন্ট কনফিগ ফাইল
    if not cred_dict and os.path.exists(PERSISTENT_FILE):
        try:
            with open(PERSISTENT_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cred_dict = saved.get("firebase_credentials")
        except Exception as e:
            logging.error(f"Failed to read {PERSISTENT_FILE}: {e}")

    # ৩. সরাসরি ফাইল
    if not cred_dict and os.path.exists(FIREBASE_KEY_PATH):
        try:
            with open(FIREBASE_KEY_PATH, "r", encoding="utf-8") as f:
                cred_dict = json.load(f)
        except Exception as e:
            logging.error(f"Failed to read {FIREBASE_KEY_PATH}: {e}")

    if cred_dict:
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            init_settings()
            logging.info("Firebase connected successfully!")
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
                "tutorial_link": "https://youtube.com",
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
    SETUP_TUTORIAL,
    SETUP_FORCE_JOIN,
    RESELLER_UID
) = range(1, 23)

def is_admin_sync(user_id: int) -> bool:
    if int(user_id) == int(SUPER_ADMIN_ID):
        return True
    if db:
        try:
            return db.collection("admins").document(str(user_id)).get().exists
        except Exception:
            return False
    return False

# --- KEYBOARDS ---
def get_user_menu(is_admin=False):
    kb = [
        [KeyboardButton("🛍️ Buy Product")],
        [KeyboardButton("👤 My Profile"), KeyboardButton("💳 Deposit")],
        [KeyboardButton("🏷️ Get Code"), KeyboardButton("💬 Support")],
        [KeyboardButton("👑 Tutorial")],
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
        [KeyboardButton("📽️ Tutorial Setup"), KeyboardButton("👑 Force Join Setup")],
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

# --- PROFILE ---
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ System offline. Please connect Firebase first.")
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

# --- SUPPORT & TUTORIAL ---
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

async def user_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = "https://youtube.com"
    if db:
        misc = db.collection("settings").document("misc").get().to_dict() or {}
        link = misc.get("tutorial_link", link)
    await update.message.reply_text(f"👑 *Tutorial & Help:*\n\nWatch our walkthrough:\n👉 {link}", parse_mode="Markdown")

# --- FIREBASE SETUP VIA BOT ---
async def ask_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return ConversationHandler.END

    msg = (
        "📁 *Permanent Firebase Setup*\n\n"
        "Please send your `serviceAccountKey.json` file as a Telegram Document.\n"
        "Once saved, it will be retained permanently across code updates."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return UPLOAD_FIREBASE_JSON

async def save_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".json"):
        await update.message.reply_text("❌ Please send a valid `.json` file.")
        return UPLOAD_FIREBASE_JSON

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    try:
        data_dict = json.loads(file_bytes.decode("utf-8"))

        with open(FIREBASE_KEY_PATH, "w", encoding="utf-8") as f:
            json.dump(data_dict, f)

        with open(PERSISTENT_FILE, "w", encoding="utf-8") as f:
            json.dump({"firebase_credentials": data_dict}, f)

        if load_firebase():
            await update.message.reply_text(
                "✅ *Firebase connected and permanently saved!*\n"
                "All functions, stock management, and databases are active.",
                parse_mode="Markdown",
                reply_markup=get_admin_menu()
            )
        else:
            await update.message.reply_text("❌ File saved, but failed to connect to Firebase.")
    except Exception as e:
        await update.message.reply_text(f"❌ JSON error: `{e}`", parse_mode="Markdown")

    return ConversationHandler.END

# --- DEPOSIT (SS / TRXID) ---
async def user_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Database is offline.")
        return ConversationHandler.END

    settings = db.collection("settings").document("payments").get().to_dict() or {}
    kb = [
        [InlineKeyboardButton("💳 bKash", callback_data="paymeth_bkash"), InlineKeyboardButton("💳 Nagad", callback_data="paymeth_nagad")],
        [InlineKeyboardButton("💳 Rocket", callback_data="paymeth_rocket"), InlineKeyboardButton("💳 Binance", callback_data="paymeth_binance")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    msg = "💳 *Deposit*\n\nSelect payment method:"
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
        f"Send Money / Transfer to: `{acc_num}`\n\n"
        f"Enter the amount in BDT you transferred:"
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
        await update.message.reply_text("❌ Please enter a valid amount (e.g. 100):")
        return DEPOSIT_AMOUNT

    await update.message.reply_text(
        "📸 Now send your *Transaction ID (TrxID)* OR send the *Payment Screenshot (SS)* as a photo:",
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
        await update.message.reply_text("⚠️ Database offline.")
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
        "✅ *Deposit request submitted!*\nAdmin will verify and credit your balance shortly.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# --- STORE (DYNAMIC CATEGORIES & COUNTER) ---
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Store is currently unavailable.")
        return

    # অ্যাডমিন যোগ করার পরই লোড হবে
    prods = db.collection("products").get()
    cats = sorted(list(set(p.to_dict().get("cat") for p in prods if p.to_dict().get("cat"))))

    if not cats:
        await update.message.reply_text("🛍️ *Store is Empty!*\nNo products have been added yet.", parse_mode="Markdown")
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

# --- BROADCAST (VOICE / TEXT / PHOTO) ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📢 *Send Broadcast Message:*\n\n"
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
    status_msg = await update.message.reply_text("🚀 Broadcasting...")
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

# --- ADD STOCK ---
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

# --- PRODUCT MANAGEMENT (ADD / PRICE / DELETE / CLEAR) ---
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    kb = [
        [InlineKeyboardButton("👑 Add New Product", callback_data="prodman_add")],
        [InlineKeyboardButton("💰 Change Price", callback_data="prodman_chprice")],
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
    elif act == "chprice":
        prods = db.collection("products").get()
        kb = [[InlineKeyboardButton(f"✏️ {p.to_dict()['name']}", callback_data=f"chpr_{p.id}")] for p in prods]
        await query.edit_message_text("Choose product to change pricing:", reply_markup=InlineKeyboardMarkup(kb))
        return CHANGE_PRICE_SELECT

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

async def delete_single_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("delp_", "")
    if db:
        db.collection("products").document(pid).delete()
    await query.edit_message_text("✅ Product deleted.")

async def clear_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("clearstock_", "")
    if db:
        stocks = db.collection("products").document(pid).collection("stocks").get()
        batch = db.batch()
        for s in stocks:
            batch.delete(s.reference)
        batch.commit()
    await query.edit_message_text("✅ Stock emptied.")

async def select_prod_for_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("chpr_", "")
    context.user_data["ch_prod_id"] = pid
    await query.edit_message_text("Enter new Regular and Reseller price (e.g. `65 60`):", parse_mode="Markdown")
    return CHANGE_PRICE_VAL

async def save_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ Enter numbers only (e.g. `65 60`):")
        return CHANGE_PRICE_VAL

    pid = context.user_data.get("ch_prod_id")
    if db:
        db.collection("products").document(pid).update({"price": price, "reseller": reseller})
    await update.message.reply_text("✅ Price updated!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- USER MANAGEMENT ---
async def user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("👥 Send User ID or Username (without @):")
    return FIND_USER

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().replace("@", "")
    target_user, target_id = None, None

    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return ConversationHandler.END

    if query.isdigit():
        doc = db.collection("users").document(query).get()
        if doc.exists:
            target_user = doc.to_dict()
            target_id = query
    else:
        results = db.collection("users").where("username", "==", query).limit(1).get()
        if results:
            target_user = results[0].to_dict()
            target_id = results[0].id

    if not target_user:
        await update.message.reply_text("❌ User not found.")
        return ConversationHandler.END

    context.user_data["target_uid"] = target_id
    balance = target_user.get("balance", 0.0)
    usd = balance / 125.0
    status = "Banned" if target_user.get("is_banned") else "Active"

    card = (
        "╔═══════════════════════════╗\n"
        "      👥  *MANAGE USER*     \n"
        "╚═══════════════════════════╝\n"
        f"• *Name:* {target_user.get('name', 'N/A')}\n"
        f"• *ID:* `{target_id}`\n"
        f"• *Username:* @{target_user.get('username', 'None')}\n"
        f"• *Balance:* `{balance:.2f} BDT` (~${usd:.2f} USD)\n"
        f"• *Orders:* `{target_user.get('orders', 0)}`\n"
        f"• *Status:* {'🚫 Banned' if status == 'Banned' else '✅ Active'}\n"
        "───────────────────────────"
    )

    kb = [
        [InlineKeyboardButton("🚫 Ban / Unban", callback_data=f"uact_ban_{target_id}")],
        [InlineKeyboardButton("➕ Add Balance", callback_data=f"uact_add_{target_id}"),
         InlineKeyboardButton("➖ Cut Balance", callback_data=f"uact_cut_{target_id}")],
        [InlineKeyboardButton("✉️ Send Message", callback_data=f"uact_msg_{target_id}")]
    ]
    await update.message.reply_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

async def user_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, uid = query.data.replace("uact_", "").split("_")
    context.user_data["action_uid"] = uid

    if not db:
        await query.edit_message_text("⚠️ Database offline.")
        return ConversationHandler.END

    if action == "ban":
        ref = db.collection("users").document(uid)
        curr = ref.get().to_dict().get("is_banned", False)
        ref.update({"is_banned": not curr})
        await query.edit_message_text(f"✅ User ID `{uid}` Ban Status: `{not curr}`", parse_mode="Markdown")
        return ConversationHandler.END
    elif action in ["add", "cut"]:
        context.user_data["bal_op"] = action
        await query.edit_message_text("Enter amount in BDT:")
        return USER_ACTION_AMOUNT
    elif action == "msg":
        await query.edit_message_text("Type the message to send to this user:")
        return USER_SEND_MSG

async def apply_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number:")
        return USER_ACTION_AMOUNT

    uid = context.user_data.get("action_uid")
    op = context.user_data.get("bal_op")
    delta = amt if op == "add" else -amt

    if db:
        db.collection("users").document(uid).update({"balance": firestore.Increment(delta)})
    await update.message.reply_text(f"✅ Balance updated by `{delta:+.2f} BDT`.", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def send_user_direct_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("action_uid")
    msg_text = update.message.text
    try:
        await context.bot.send_message(
            chat_id=int(uid),
            text=f"💬 *Message from Admin:*\n\n{msg_text}",
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ Message sent!", reply_markup=get_admin_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to deliver: {e}")
    return ConversationHandler.END

# --- DEPOSIT APPROVAL / REJECTION & HISTORY ---
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
        if query.message.photo:
            await query.edit_message_caption(caption="⚠️ Already processed.")
        else:
            await query.edit_message_text("⚠️ Already processed.")
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

async def deposit_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return
    history = db.collection("deposit_requests").order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).get()
    if not history:
        await update.message.reply_text("No deposit records.")
        return
    msg = "⚙️ *Recent Deposit History:*\n━━━━━━━━━━━━━━━━━━━━\n"
    for h in history:
        d = h.to_dict()
        msg += f"• `{d['user_id']}` | `{d['amount']} BDT` | {d['method'].upper()} | `{d['status'].upper()}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- PAYMENT SETTINGS ---
async def payment_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return
    data = db.collection("settings").document("payments").get().to_dict() or {}
    rate = data.get("dollar_rate", 125.0)

    keyboard = [
        [InlineKeyboardButton("Edit bKash Number", callback_data="payedit_bkash")],
        [InlineKeyboardButton("Edit Nagad Number", callback_data="payedit_nagad")],
        [InlineKeyboardButton("Edit Rocket Number", callback_data="payedit_rocket")],
        [InlineKeyboardButton("Edit Binance Pay ID", callback_data="payedit_binance")],
        [InlineKeyboardButton(f"Edit Dollar Rate (Current: {rate:.1f} BDT)", callback_data="payedit_dollar_rate")],
    ]
    await update.message.reply_text("💳 *Select Payment Setting to Update:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_payment_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("payedit_", "")
    context.user_data["editing_pay_field"] = field
    await query.edit_message_text(f"Send the new value for `{field}`:", parse_mode="Markdown")
    return EDIT_PAYMENT_VALUE

async def save_payment_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    field = context.user_data.get("editing_pay_field")
    if field == "dollar_rate":
        try:
            val = float(val)
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number:")
            return EDIT_PAYMENT_VALUE

    if db:
        db.collection("settings").document("payments").update({field: val})
    await update.message.reply_text(f"✅ Updated `{field}`!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- VOUCHER MANAGEMENT (REDEEM / CREATE) ---
async def get_code_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏷️ *Enter your Voucher Code:*", parse_mode="Markdown")
    return REDEEM_VOUCHER

async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    user_id = str(update.effective_user.id)
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return ConversationHandler.END

    doc = db.collection("vouchers").document(code).get()
    if not doc.exists:
        await update.message.reply_text("❌ Invalid code.")
        return ConversationHandler.END

    v_data = doc.to_dict()
    if v_data.get("used"):
        await update.message.reply_text("❌ Voucher already claimed.")
        return ConversationHandler.END

    amount = v_data.get("amount", 0.0)
    doc.reference.update({"used": True, "used_by": user_id})
    db.collection("users").document(user_id).update({"balance": firestore.Increment(amount)})

    await update.message.reply_text(f"🎉 *Success!* `{amount:.2f} BDT` has been added to your balance.", parse_mode="Markdown")
    return ConversationHandler.END

async def voucher_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return ConversationHandler.END
    await update.message.reply_text("Enter new Voucher/Promo Code (e.g. `OFFER50`):", parse_mode="Markdown")
    return ADD_VOUCHER_CODE

async def get_v_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_v_code"] = update.message.text.strip().upper()
    await update.message.reply_text("Enter reward amount in BDT:")
    return ADD_VOUCHER_BAL

async def get_v_bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Enter numbers only:")
        return ADD_VOUCHER_BAL

    code = context.user_data.get("new_v_code")
    if db:
        db.collection("vouchers").document(code).set({
            "amount": amt,
            "used": False,
            "created_at": firestore.SERVER_TIMESTAMP
        })
    await update.message.reply_text(f"✅ Voucher `{code}` created for `{amt:.2f} BDT`!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ADMIN MANAGEMENT ---
async def admin_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if int(update.effective_user.id) != int(SUPER_ADMIN_ID):
        return
    kb = [
        [InlineKeyboardButton("👑 Add Admin", callback_data="admin_add")],
        [InlineKeyboardButton("❌ Remove Admin", callback_data="admin_del")]
    ]
    await update.message.reply_text("👑 *Admin Management*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_admin_manage_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("admin_", "")
    if act == "add":
        await query.edit_message_text("Send Telegram Numeric User ID of new admin:")
        return ADD_ADMIN_ID
    else:
        if db:
            admins = db.collection("admins").get()
            kb = [[InlineKeyboardButton(f"❌ {a.id}", callback_data=f"deladm_{a.id}")] for a in admins]
            await query.edit_message_text("Select admin to remove:", reply_markup=InlineKeyboardMarkup(kb))

async def save_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.message.text.strip()
    if not aid.isdigit():
        await update.message.reply_text("❌ Numeric ID only:")
        return ADD_ADMIN_ID
    if db:
        db.collection("admins").document(aid).set({"role": "admin"})
    await update.message.reply_text(f"✅ User ID `{aid}` is now an admin!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def del_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    aid = query.data.replace("deladm_", "")
    if db:
        db.collection("admins").document(aid).delete()
    await query.edit_message_text(f"✅ Admin `{aid}` removed!")

# --- RESELLER, SUPPORT, TUTORIAL, FORCE JOIN ---
async def reseller_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("Send User ID to toggle Reseller status:")
    return RESELLER_UID

async def save_reseller_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text.strip()
    if not db:
        return ConversationHandler.END
    ref = db.collection("users").document(uid)
    doc = ref.get()
    if not doc.exists:
        await update.message.reply_text("❌ User not found.")
        return ConversationHandler.END

    status = not doc.to_dict().get("is_reseller", False)
    ref.update({"is_reseller": status})
    await update.message.reply_text(f"✅ Reseller status for `{uid}`: `{'Active' if status else 'Revoked'}`", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("Send Support URL or username (e.g. `https://t.me/admin`):")
    return SETUP_SUPPORT

async def save_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if db:
        db.collection("settings").document("misc").update({"support_link": link})
    await update.message.reply_text("✅ Support link saved!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("Send Tutorial Video URL:")
    return SETUP_TUTORIAL

async def save_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if db:
        db.collection("settings").document("misc").update({"tutorial_link": link})
    await update.message.reply_text("✅ Tutorial link saved!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("Send Force Join channel username (e.g. `@MyChannel`):")
    return SETUP_FORCE_JOIN

async def save_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    if db:
        db.collection("settings").document("misc").update({"force_channel": ch})
    await update.message.reply_text("✅ Force Join Channel updated!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- CANCEL & NOOP ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action canceled.", reply_markup=get_user_menu(is_admin_sync(update.effective_user.id)))
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

    # Firebase Setup
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

    # Product Add & Price Change
    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_add$"),
            CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_chprice$"),
            CallbackQueryHandler(select_prod_for_price, pattern=r"^chpr_"),
        ],
        states={
            ADD_PROD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_cat)],
            ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_name)],
            ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_price)],
            CHANGE_PRICE_SELECT: [CallbackQueryHandler(select_prod_for_price, pattern=r"^chpr_")],
            CHANGE_PRICE_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Broadcast (Text / Voice / Photo)
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast$"), start_broadcast)],
        states={BROADCAST_RECEIVE: [MessageHandler((filters.TEXT | filters.VOICE | filters.PHOTO) & ~filters.COMMAND, execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Voucher Redeem
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Get Code$"), get_code_prompt)],
        states={REDEEM_VOUCHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_code)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Voucher Create
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Voucher Management$"), voucher_management)],
        states={
            ADD_VOUCHER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_code)],
            ADD_VOUCHER_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_bal)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # User Management
    app.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^👥 User Management$"), user_management),
            CallbackQueryHandler(user_actions_callback, pattern=r"^uact_(add|cut|msg)_")
        ],
        states={
            FIND_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_user)],
            USER_ACTION_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_user_balance)],
            USER_SEND_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_user_direct_msg)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Payment Settings
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_payment_edit, pattern=r"^payedit_")],
        states={EDIT_PAYMENT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_payment_value)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Add Admin
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_add$")],
        states={ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_admin)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Reseller, Support, Tutorial, Force Join
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🤝 Reseller Management$"), reseller_management)],
        states={RESELLER_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reseller_toggle)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠️ Support Setup$"), prompt_support_setup)],
        states={SETUP_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_support_setup)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📽️ Tutorial Setup$"), prompt_tutorial_setup)],
        states={SETUP_TUTORIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tutorial_setup)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👑 Force Join Setup$"), prompt_force_join)],
        states={SETUP_FORCE_JOIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_force_join)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Main Menus
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ Buy Product$"), buy_products_menu))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^💬 Support$"), user_support))
    app.add_handler(MessageHandler(filters.Regex("^👑 Tutorial$"), user_tutorial))
    app.add_handler(MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^💼 Product Management$"), product_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^📊 Live Stock$"), live_stock))
    app.add_handler(MessageHandler(filters.Regex("^📦 Add Stock$"), add_stock_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔔 Deposit Requests$"), show_deposit_requests))
    app.add_handler(MessageHandler(filters.Regex("^📜 Deposit History$"), deposit_history))
    app.add_handler(MessageHandler(filters.Regex("^💳 Payment Settings$"), payment_settings))
    app.add_handler(MessageHandler(filters.Regex("^🔑 Admin Management$"), admin_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^(🔙 User Menu|✅ User Menu)$"), start))

    # Callbacks
    app.add_handler(CallbackQueryHandler(buy_products_menu, pattern=r"^back_to_cats$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^cancel_action$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(handle_buy_cat, pattern=r"^buycat_"))
    app.add_handler(CallbackQueryHandler(show_purchase_summary, pattern=r"^selpkg_"))
    app.add_handler(CallbackQueryHandler(update_quantity_callback, pattern=r"^qty_(inc|dec)_"))
    app.add_handler(CallbackQueryHandler(confirm_purchase, pattern=r"^buy_confirm_"))
    app.add_handler(CallbackQueryHandler(handle_deposit_decide, pattern=r"^dep(app|rej)_"))
    app.add_handler(CallbackQueryHandler(delete_single_product, pattern=r"^delp_"))
    app.add_handler(CallbackQueryHandler(clear_product_stock, pattern=r"^clearstock_"))
    app.add_handler(CallbackQueryHandler(del_admin_cb, pattern=r"^deladm_"))
    app.add_handler(CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_del$"))

    # Render Port Server
    await start_web_server()

    async with app:
        await app.start()
        await app.updater.start_polling()
        logging.info("Bot is polling and Web Service is running...")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(run_bot())