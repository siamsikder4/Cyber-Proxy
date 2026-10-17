import os
import io
import json
import asyncio
import logging
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
BOT_TOKEN = "8868386011:AAEulcSqsAr2DxvBLRdMNANzDfCak5MN64Q"  # আপনার বট টোকেন
SUPER_ADMIN_ID = 8271633124                  # আপনার টেলিগ্রাম আইডি (সংখ্যা)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

FIREBASE_KEY_PATH = "serviceAccountKey.json"
db = None

# --- FIREBASE CONNECTOR ---
def load_firebase():
    global db
    if os.path.exists(FIREBASE_KEY_PATH):
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_KEY_PATH)
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            init_defaults()
            logging.info("Firebase connected successfully!")
            return True
        except Exception as e:
            logging.error(f"Firebase connection error: {e}")
            db = None
            return False
    return False

def init_defaults():
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
                "dollar_rate": 120.0
            })

        misc_ref = db.collection("settings").document("misc")
        if not misc_ref.get().exists:
            misc_ref.set({
                "support_link": "https://t.me/your_support",
                "tutorial_link": "https://youtube.com",
                "force_channel": ""
            })

        prods = db.collection("products").limit(1).get()
        if len(prods) == 0:
            defaults = [
                {"cat": "Proxy~IP", "name": "1GB USA Proxy (1 Month)", "price": 75.0, "reseller": 70.0},
                {"cat": "Proxy~IP", "name": "Rapid Proxy 200 MB", "price": 40.0, "reseller": 35.0},
                {"cat": "Proxy~IP", "name": "Owl Proxy 200 MB", "price": 15.0, "reseller": 12.0},
                {"cat": "Hotmail", "name": "Hotmail Fresh Account", "price": 10.0, "reseller": 8.0},
                {"cat": "Outlook", "name": "Outlook Aged Account", "price": 12.0, "reseller": 10.0},
                {"cat": "FR_Outlook", "name": "FR Outlook Account", "price": 15.0, "reseller": 12.0},
                {"cat": "VPN", "name": "NordVPN Premium (1 Month)", "price": 120.0, "reseller": 100.0},
            ]
            for item in defaults:
                db.collection("products").add(item)
    except Exception as e:
        logging.error(f"Error seeding default settings: {e}")

# Conversation States
(
    UPLOAD_FIREBASE_JSON,
    UPLOAD_STOCK,
    FIND_USER,
    USER_ACTION_AMOUNT,
    USER_SEND_MSG,
    EDIT_PAYMENT_VALUE,
    DEPOSIT_AMOUNT,
    DEPOSIT_TRX,
    ADD_PROD_CAT,
    ADD_PROD_NAME,
    ADD_PROD_PRICE,
    CHANGE_PRICE_SELECT,
    CHANGE_PRICE_VAL,
    BROADCAST_MSG,
    ADD_VOUCHER_CODE,
    ADD_VOUCHER_BAL,
    REDEEM_VOUCHER,
    ADD_ADMIN_ID,
    SETUP_SUPPORT,
    SETUP_TUTORIAL,
    SETUP_FORCE_JOIN,
    RESELLER_UID
) = range(1, 23)

# --- কড়া ও নিখুঁত অ্যাডমিন চেকার ---
def is_admin_sync(user_id: int) -> bool:
    if int(user_id) == int(SUPER_ADMIN_ID):
        return True
    if db:
        try:
            return db.collection("admins").document(str(user_id)).get().exists
        except Exception:
            return False
    return False

# --- কীবোর্ড জেনারেটর ---
def get_user_menu(is_admin=False):
    kb = [
        [KeyboardButton("🎟️ Buy Products")],
        [KeyboardButton("🧑‍💼 My Profile"), KeyboardButton("💵 Deposit")],
        [KeyboardButton("🛡️ Redeem Code"), KeyboardButton("💬 Support")],
        [KeyboardButton("👑 Tutorial")],
    ]
    if is_admin:
        kb.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_admin_menu():
    kb = [
        [KeyboardButton("💼 Product Management"), KeyboardButton("🔥 Add Stock")],
        [KeyboardButton("🌐 Live Stock"), KeyboardButton("👥 User Management")],
        [KeyboardButton("🔔 Deposit Requests"), KeyboardButton("⚙️ Deposit History")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("🏷️ Voucher Management")],
        [KeyboardButton("👑 Force Join Setup"), KeyboardButton("🧰 Support Setup")],
        [KeyboardButton("🔑 Admin Management"), KeyboardButton("💳 Payment Settings")],
        [KeyboardButton("🤝 Reseller Management"), KeyboardButton("📽️ Tutorial Setup")],
        [KeyboardButton("🔥 Setup Firebase"), KeyboardButton("✅ User Menu")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# --- START COMMAND ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = is_admin_sync(user.id)

    if db:
        try:
            user_ref = db.collection("users").document(str(user.id))
            if not user_ref.get().exists:
                user_ref.set({
                    "name": user.full_name,
                    "username": user.username or "None",
                    "balance": 0.0,
                    "orders": 0,
                    "is_banned": False,
                    "is_reseller": False
                })
            else:
                user_ref.update({"name": user.full_name, "username": user.username or "None"})
        except Exception as e:
            logging.error(f"Error registering user: {e}")

    if not db and is_admin:
        msg = (
            "⚠️ *Database Status: Offline / Not Connected*\n\n"
            "Firebase is not connected yet. Click *👑 Admin Panel* below and choose "
            "*🔥 Setup Firebase* to upload your `serviceAccountKey.json`."
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_user_menu(is_admin=True))
        return

    welcome_msg = (
        f"👋 *Welcome, {user.first_name}!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Select an option from the menu below to start shopping or managing your account."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_user_menu(is_admin))

# --- ADMIN PANEL ACCESS ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin_sync(user_id):
        await update.message.reply_text("⛔ *Access Denied:* You are not authorized to use the admin panel.", parse_mode="Markdown")
        return
    await update.message.reply_text("👑 *Admin Control Panel*", reply_markup=get_admin_menu(), parse_mode="Markdown")

# --- FIREBASE SETUP VIA TELEGRAM ---
async def ask_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return ConversationHandler.END

    msg = (
        "📁 *Upload Firebase Configuration*\n\n"
        "Please send your `serviceAccountKey.json` file as a Telegram Document.\n"
        "Send /cancel to abort."
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
        json.loads(file_bytes.decode("utf-8"))
        with open(FIREBASE_KEY_PATH, "wb") as f:
            f.write(file_bytes)

        if load_firebase():
            await update.message.reply_text(
                "✅ *Firebase connected successfully!*\nAll systems and database records are live.",
                parse_mode="Markdown",
                reply_markup=get_admin_menu()
            )
        else:
            await update.message.reply_text("❌ File saved, but failed to connect to Firebase.")
    except Exception as e:
        await update.message.reply_text(f"❌ JSON error: `{e}`", parse_mode="Markdown")

    return ConversationHandler.END

# --- USER PROFILE & LINKS ---
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Database offline. Please connect Firebase first.")
        return
    user_id = str(update.effective_user.id)
    data = db.collection("users").document(user_id).get().to_dict() or {}
    balance = data.get("balance", 0.0)
    usd = balance / 120.0
    status = "Active" if not data.get("is_banned") else "Banned"

    profile_card = (
        "╔═══════════════════════════╗\n"
        "       👤  *USER PROFILE*    \n"
        "╚═══════════════════════════╝\n"
        f"• *Name:* {data.get('name', 'N/A')}\n"
        f"• *User ID:* `{user_id}`\n"
        f"• *Username:* @{data.get('username', 'None')}\n"
        f"• *Tier:* {'⭐ Reseller' if data.get('is_reseller') else 'Regular User'}\n"
        f"• *Balance:* `{balance:.2f} BDT` (~${usd:.2f} USD)\n"
        f"• *Total Orders:* `{data.get('orders', 0)}`\n"
        f"• *Status:* {'✅ Active' if status == 'Active' else '🚫 Banned'}\n"
        "───────────────────────────"
    )
    await update.message.reply_text(profile_card, parse_mode="Markdown")

async def user_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = "https://t.me"
    if db:
        misc = db.collection("settings").document("misc").get().to_dict() or {}
        link = misc.get("support_link", link)
    await update.message.reply_text(f"💬 *Support Desk:*\n\nGet help directly here:\n👉 {link}", parse_mode="Markdown")

async def user_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = "https://youtube.com"
    if db:
        misc = db.collection("settings").document("misc").get().to_dict() or {}
        link = misc.get("tutorial_link", link)
    await update.message.reply_text(f"👑 *Tutorial & Help:*\n\nWatch our walkthrough:\n👉 {link}", parse_mode="Markdown")

# --- USER DEPOSIT ---
async def user_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Database offline. Please try again later.")
        return ConversationHandler.END

    settings = db.collection("settings").document("payments").get().to_dict() or {}
    kb = [
        [InlineKeyboardButton("bKash (Personal)", callback_data="paymeth_bkash"), InlineKeyboardButton("Nagad (Personal)", callback_data="paymeth_nagad")],
        [InlineKeyboardButton("Rocket (Personal)", callback_data="paymeth_rocket"), InlineKeyboardButton("Binance (USDT)", callback_data="paymeth_binance")]
    ]
    deposit_msg = (
        "💳 *AUTOMATED DEPOSIT SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"• *bKash (Personal):* `{settings.get('bkash')}`\n"
        f"• *Nagad (Personal):* `{settings.get('nagad')}`\n"
        f"• *Rocket (Personal):* `{settings.get('rocket')}`\n"
        f"• *Binance Pay ID:* `{settings.get('binance')}`\n\n"
        f"💵 *Exchange Rate:* 1 USD = `{settings.get('dollar_rate', 120.0)} BDT`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select your deposit payment method:"
    )
    await update.message.reply_text(deposit_msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_method_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("paymeth_", "")
    context.user_data["dep_method"] = method
    await query.edit_message_text(f"Selected: *{method.upper()}*\n\nEnter the amount in BDT you transferred:", parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        if amt <= 0:
            raise ValueError()
        context.user_data["dep_amount"] = amt
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g. 500):")
        return DEPOSIT_AMOUNT

    await update.message.reply_text("Now send your *Transaction ID (TrxID)*:", parse_mode="Markdown")
    return DEPOSIT_TRX

async def deposit_trx_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trx = update.message.text.strip()
    uid = str(update.effective_user.id)
    amt = context.user_data.get("dep_amount")
    method = context.user_data.get("dep_method")

    if not db:
        await update.message.reply_text("⚠️ Database connection lost.")
        return ConversationHandler.END

    req_ref = db.collection("deposit_requests").add({
        "user_id": uid,
        "amount": amt,
        "method": method,
        "trx": trx,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    req_id = req_ref[1].id

    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{req_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{req_id}")
        ]
    ]
    try:
        await context.bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=(
                f"🔔 *NEW DEPOSIT REQUEST*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• User: `{uid}`\n"
                f"• Amount: `{amt:.2f} BDT`\n"
                f"• Method: `{method.upper()}`\n"
                f"• TrxID: `{trx}`"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        logging.error(f"Deposit notification failed: {e}")

    await update.message.reply_text("✅ *Deposit submitted!* Admin will verify and credit your balance shortly.", parse_mode="Markdown")
    return ConversationHandler.END

# --- VOUCHER REDEEM ---
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

# --- BUYING FLOW ---
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📧 Hotmail", callback_data="buycat_Hotmail"),
         InlineKeyboardButton("📧 Outlook", callback_data="buycat_Outlook")],
        [InlineKeyboardButton("📧 FR_Outlook", callback_data="buycat_FR_Outlook"),
         InlineKeyboardButton("🔒 VPN", callback_data="buycat_VPN")],
        [InlineKeyboardButton("🌐 Proxy~IP", callback_data="buycat_Proxy~IP")]
    ]
    await update.message.reply_text("🗂️ *Choose a Category:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_buy_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("buycat_", "")

    if not db:
        await query.edit_message_text("⚠️ Database offline.")
        return

    prods = db.collection("products").where("cat", "==", category).get()
    if not prods:
        await query.edit_message_text(f"❌ No products under *{category}*.", parse_mode="Markdown")
        return

    buttons = []
    for p in prods:
        p_data = p.to_dict()
        stock_count = len(p.reference.collection("stocks").get())
        text = f"🌐 {p_data['name']} | {p_data['price']:.1f}৳ | Stock: {stock_count}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"order_{p.id}")])

    await query.edit_message_text(f"📦 *Items under {category}:*", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def handle_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    prod_id = query.data.replace("order_", "")

    if not db:
        await query.answer("⚠️ Database offline.", show_alert=True)
        return

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

    stock_query = prod_ref.collection("stocks").limit(1).get()
    if not stock_query:
        await query.answer("❌ Out of stock!", show_alert=True)
        return

    price = prod_doc["reseller"] if user_doc.get("is_reseller") else prod_doc["price"]
    if user_doc.get("balance", 0.0) < price:
        await query.answer("❌ Insufficient balance! Please deposit first.", show_alert=True)
        return

    stock_item = stock_query[0]
    stock_data = stock_item.to_dict().get("data")
    stock_item.reference.delete()

    user_ref.update({
        "balance": firestore.Increment(-price),
        "orders": firestore.Increment(1)
    })

    receipt = (
        "╔═══════════════════════════╗\n"
        "   ✅  *PURCHASE SUCCESSFUL* \n"
        "╚═══════════════════════════╝\n"
        f"• *Product:* {prod_doc['name']}\n"
        f"• *Charged:* `{price:.2f} BDT`\n\n"
        f"🔑 *Delivery Credentials:*\n`{stock_data}`\n"
        "───────────────────────────"
    )
    await query.edit_message_text(receipt, parse_mode="Markdown")

# --- LIVE STOCK ---
async def live_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Database offline. Setup Firebase first.")
        return
    prods = db.collection("products").get()
    msg = (
        "╔═══════════════════════════╗\n"
        "      🌐  *LIVE STOCK FEED* \n"
        "╚═══════════════════════════╝\n\n"
    )
    for p in prods:
        d = p.to_dict()
        count = len(p.reference.collection("stocks").get())
        msg += f"📦 *{d['name']}*\n• Price: `{d['price']:.1f}৳` | Reseller: `{d.get('reseller', d['price']):.1f}৳`\n• Available: `{count}`\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- ADD STOCK ---
async def add_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return
    keyboard = [
        [InlineKeyboardButton("📧 Hotmail", callback_data="stockcat_Hotmail"),
         InlineKeyboardButton("📧 Outlook", callback_data="stockcat_Outlook")],
        [InlineKeyboardButton("📧 FR_Outlook", callback_data="stockcat_FR_Outlook"),
         InlineKeyboardButton("🌐 Proxy~IP", callback_data="stockcat_Proxy~IP")]
    ]
    await update.message.reply_text("🗂️ *Choose category to add stock:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_stock_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("stockcat_", "")

    prods = db.collection("products").where("cat", "==", category).get()
    buttons = [[InlineKeyboardButton(p.to_dict()["name"], callback_data=f"upstock_{p.id}")] for p in prods]
    await query.edit_message_text(f"Select product under *{category}*:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

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
        f"✏️ *If TXT File:*\n"
        f"`Host:Port:Username:Password`\n\n"
        f"🧪 *If Excel File:*\n"
        f"• Column A = Host\n"
        f"• Column B = Port\n"
        f"• Column C = Username\n"
        f"• Column D = Password"
    )
    await query.edit_message_text(instruction, parse_mode="Markdown")
    return UPLOAD_STOCK

async def process_stock_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    prod_id = context.user_data.get("upload_prod_id")
    if not prod_id or not db:
        await update.message.reply_text("❌ Product ID or DB missing.")
        return ConversationHandler.END

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    entries = []

    if doc.file_name.endswith(".txt"):
        lines = file_bytes.decode("utf-8", errors="ignore").splitlines()
        for line in lines:
            line = line.strip()
            if line:
                entries.append(line)
    elif doc.file_name.endswith(".xlsx"):
        wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active
        for row in sheet.iter_rows(values_only=True):
            if any(row):
                line = ":".join(str(cell).strip() for cell in row[:4] if cell is not None)
                entries.append(line)

    if entries:
        prod_ref = db.collection("products").document(prod_id)
        batch = db.batch()
        for item in entries:
            ref = prod_ref.collection("stocks").document()
            batch.set(ref, {"data": item})
        batch.commit()

        await update.message.reply_text(f"✅ Loaded `{len(entries)}` items into stock!", parse_mode="Markdown", reply_markup=get_admin_menu())
    else:
        await update.message.reply_text("❌ No data found.")
    return ConversationHandler.END

# --- PRODUCT MANAGEMENT ---
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    kb = [
        [InlineKeyboardButton("👑 Add Product", callback_data="prodman_add"),
         InlineKeyboardButton("💰 Change Price", callback_data="prodman_chprice")],
        [InlineKeyboardButton("❌ Delete Product", callback_data="prodman_delprod"),
         InlineKeyboardButton("🧨 Clear Stock", callback_data="prodman_delstock")],
    ]
    await update.message.reply_text("⚙️ *Product Management Console*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_prodman_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("prodman_", "")

    if not db:
        await query.edit_message_text("⚠️ Database offline.")
        return

    if act == "add":
        kb = [
            [InlineKeyboardButton("📧 Hotmail", callback_data="setcat_Hotmail"), InlineKeyboardButton("📧 Outlook", callback_data="setcat_Outlook")],
            [InlineKeyboardButton("📧 FR_Outlook", callback_data="setcat_FR_Outlook"), InlineKeyboardButton("🔒 VPN", callback_data="setcat_VPN")],
            [InlineKeyboardButton("🌐 Proxy~IP", callback_data="setcat_Proxy~IP")]
        ]
        await query.edit_message_text("Select category:", reply_markup=InlineKeyboardMarkup(kb))
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
        await query.edit_message_text("Select product to modify price:", reply_markup=InlineKeyboardMarkup(kb))
        return CHANGE_PRICE_SELECT

async def save_add_prod_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("setcat_", "")
    context.user_data["new_prod_cat"] = cat
    await query.edit_message_text(f"Category: *{cat}*\n\nSend Product Name:", parse_mode="Markdown")
    return ADD_PROD_NAME

async def save_add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_prod_name"] = update.message.text.strip()
    await update.message.reply_text("Enter Regular and Reseller price separated by space (e.g. `50 45`):", parse_mode="Markdown")
    return ADD_PROD_PRICE

async def save_add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ Send numbers only (e.g. `50 45`):")
        return ADD_PROD_PRICE

    if db:
        db.collection("products").add({
            "cat": context.user_data.get("new_prod_cat"),
            "name": context.user_data.get("new_prod_name"),
            "price": price,
            "reseller": reseller
        })
    await update.message.reply_text("✅ Product added successfully!", reply_markup=get_admin_menu())
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
    usd = balance / 120.0
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

# --- DEPOSIT APPROVAL / REJECT ---
async def show_deposit_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database offline.")
        return

    reqs = db.collection("deposit_requests").where("status", "==", "pending").get()
    if not reqs:
        await update.message.reply_text("✅ No pending deposits.")
        return

    for r in reqs:
        d = r.to_dict()
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{r.id}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{r.id}")]]
        await update.message.reply_text(
            f"🔔 *PENDING DEPOSIT*\n"
            f"• User: `{d['user_id']}`\n"
            f"• Amount: `{d['amount']:.2f} BDT`\n"
            f"• Method: `{d['method'].upper()}`\n"
            f"• TrxID: `{d['trx']}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def handle_deposit_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act, req_id = query.data.split("_")

    if not db:
        await query.edit_message_text("⚠️ Database offline.")
        return

    ref = db.collection("deposit_requests").document(req_id)
    doc = ref.get()
    if not doc.exists:
        await query.edit_message_text("❌ Request not found.")
        return

    data = doc.to_dict()
    if data["status"] != "pending":
        await query.edit_message_text("⚠️ Already processed.")
        return

    if act == "depapp":
        ref.update({"status": "approved"})
        db.collection("users").document(data["user_id"]).update({"balance": firestore.Increment(data["amount"])})
        try:
            await context.bot.send_message(
                chat_id=int(data["user_id"]),
                text=f"✅ *Deposit Approved!*\n`{data['amount']:.2f} BDT` added to your balance.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await query.edit_message_text(f"✅ Approved: `{data['amount']:.2f} BDT`", parse_mode="Markdown")
    else:
        ref.update({"status": "rejected"})
        try:
            await context.bot.send_message(
                chat_id=int(data["user_id"]),
                text=f"❌ Your deposit request of `{data['amount']:.2f} BDT` was rejected.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await query.edit_message_text(f"❌ Rejected: `{data['amount']:.2f} BDT`", parse_mode="Markdown")

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
    rate = data.get("dollar_rate", 120.0)

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

# --- BROADCAST ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("⚠️ Database is offline. Please setup Firebase first.")
        return ConversationHandler.END
    await update.message.reply_text("📢 *Send the broadcast message to send to all users:*", parse_mode="Markdown")
    return BROADCAST_MSG

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("⚠️ Database connection missing.")
        return ConversationHandler.END

    msg = update.message.text
    try:
        users = db.collection("users").get()
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch users: {e}")
        return ConversationHandler.END

    success, failed = 0, 0
    status_msg = await update.message.reply_text("🚀 Broadcasting...")
    for u in users:
        try:
            await context.bot.send_message(chat_id=int(u.id), text=msg)
            success += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(f"📢 *Broadcast Report:*\n\n✅ Sent: `{success}`\n❌ Failed: `{failed}`", parse_mode="Markdown")
    return ConversationHandler.END

# --- VOUCHER CREATION ---
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

# --- ADMIN DELEGATION ---
async def admin_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
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
    await update.message.reply_text("Send Support URL or username:")
    return SETUP_SUPPORT

async def save_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if db:
        db.collection("settings").document("misc").update({"support_link": link})
    await update.message.reply_text("✅ Support link updated!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_sync(update.effective_user.id):
        return
    await update.message.reply_text("Send Tutorial URL:")
    return SETUP_TUTORIAL

async def save_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if db:
        db.collection("settings").document("misc").update({"tutorial_link": link})
    await update.message.reply_text("✅ Tutorial link updated!", reply_markup=get_admin_menu())
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

# --- CANCEL & ERROR HANDLER ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action canceled.", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling an update:", exc_info=context.error)

# --- RENDER WEB SERVICE HEALTH CHECK SERVER ---
async def health_check(request):
    return web.Response(text="Bot is running and healthy!")

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Render Web Service listener running on port {port}...")

# --- MAIN RUNNER (CONCURRENT POLLING + WEB SERVER) ---
async def run_bot():
    load_firebase()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_error_handler(error_handler)

    # Setup Firebase JSON
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔥 Setup Firebase$"), ask_firebase_json)],
        states={UPLOAD_FIREBASE_JSON: [MessageHandler(filters.Document.ALL, save_firebase_json)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Add Stock
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_prepare_upload, pattern=r"^upstock_")],
        states={UPLOAD_STOCK: [MessageHandler(filters.Document.ALL, process_stock_file)]},
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

    # Deposit
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💵 Deposit$"), user_deposit_start)],
        states={
            DEPOSIT_AMOUNT: [
                CallbackQueryHandler(deposit_method_picked, pattern=r"^paymeth_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount_received)
            ],
            DEPOSIT_TRX: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_trx_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Voucher Redeem
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛡️ Redeem Code$"), get_code_prompt)],
        states={REDEEM_VOUCHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_code)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Voucher Management
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Voucher Management$"), voucher_management)],
        states={
            ADD_VOUCHER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_code)],
            ADD_VOUCHER_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_bal)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Product Add & Change Price
    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_add$"),
            CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_chprice$"),
            CallbackQueryHandler(select_prod_for_price, pattern=r"^chpr_"),
        ],
        states={
            ADD_PROD_CAT: [CallbackQueryHandler(save_add_prod_cat, pattern=r"^setcat_")],
            ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_name)],
            ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_add_prod_price)],
            CHANGE_PRICE_SELECT: [CallbackQueryHandler(select_prod_for_price, pattern=r"^chpr_")],
            CHANGE_PRICE_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Broadcast
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast$"), start_broadcast)],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Add Admin
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_add$")],
        states={ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_admin)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # Miscellaneous setups
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🤝 Reseller Management$"), reseller_management)],
        states={RESELLER_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reseller_toggle)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧰 Support Setup$"), prompt_support_setup)],
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

    # Menu Triggers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🎟️ Buy Products$"), buy_products_menu))
    app.add_handler(MessageHandler(filters.Regex("^🧑‍💼 My Profile$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^💬 Support$"), user_support))
    app.add_handler(MessageHandler(filters.Regex("^👑 Tutorial$"), user_tutorial))
    app.add_handler(MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^💼 Product Management$"), product_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^🌐 Live Stock$"), live_stock))
    app.add_handler(MessageHandler(filters.Regex("^🔥 Add Stock$"), add_stock_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔔 Deposit Requests$"), show_deposit_requests))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Deposit History$"), deposit_history))
    app.add_handler(MessageHandler(filters.Regex("^🔑 Admin Management$"), admin_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^💳 Payment Settings$"), payment_settings))
    app.add_handler(MessageHandler(filters.Regex("^✅ User Menu$"), start))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_buy_cat, pattern=r"^buycat_"))
    app.add_handler(CallbackQueryHandler(handle_order, pattern=r"^order_"))
    app.add_handler(CallbackQueryHandler(handle_stock_cat, pattern=r"^stockcat_"))
    app.add_handler(CallbackQueryHandler(user_actions_callback, pattern=r"^uact_ban_"))
    app.add_handler(CallbackQueryHandler(handle_deposit_decide, pattern=r"^dep(app|rej)_"))
    app.add_handler(CallbackQueryHandler(delete_single_product, pattern=r"^delp_"))
    app.add_handler(CallbackQueryHandler(clear_product_stock, pattern=r"^clearstock_"))
    app.add_handler(CallbackQueryHandler(del_admin_cb, pattern=r"^deladm_"))
    app.add_handler(CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_del$"))

    # Render-এর জন্য Web Service ব্যাকগ্রাউন্ডে চালু করা
    await start_web_server()

    # বট শুরু করা
    async with app:
        await app.start()
        await app.updater.start_polling()
        logging.info("Bot is polling and Web Service is active...")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(run_bot())