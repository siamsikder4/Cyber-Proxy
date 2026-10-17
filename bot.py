import os
import io
import json
import logging
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
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

# --- RENDER WEB SERVICE PORT LISTENER (GET & HEAD) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Web Service Active!")

    def log_message(self, format, *args):
        return

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Render port listening on {port}...")
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# --- CONFIGURATION ---
BOT_TOKEN = "8868386011:AAEulcSqsAr2DxvBLRdMNANzDfCak5MN64Q"
SUPER_ADMIN_ID = 8271633124
LOCAL_KEY_PATH = "serviceAccountKey.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- পার্মানেন্ট লোকাল ডাটাবেজ (SQLite) ---
def get_db():
    conn = sqlite3.connect("permanent_market.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_local_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            username TEXT,
            balance REAL DEFAULT 0.0,
            orders INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            is_reseller INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            name TEXT,
            price REAL,
            reseller_price REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            data TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            val TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vouchers (
            code TEXT PRIMARY KEY,
            amount REAL,
            used INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS deposit_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            method TEXT,
            proof TEXT,
            photo_id TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    
    # ডিফল্ট কনফিগারেশন
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('bkash', '01XXXXXXXXX')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('nagad', '01XXXXXXXXX')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('rocket', '01XXXXXXXXX')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('binance', '1266509663')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('dollar_rate', '125.0')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('support_link', 'https://t.me/your_admin')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('tutorial_link', 'https://youtube.com')")
    c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES ('force_channel', '')")
    conn.commit()
    conn.close()

init_local_db()

# --- ফায়ারবেস হ্যান্ডলার ---
firestore_db = None

def try_connect_firebase():
    global firestore_db
    paths = [LOCAL_KEY_PATH, "/etc/secrets/serviceAccountKey.json"]
    for p in paths:
        if os.path.exists(p):
            try:
                if not firebase_admin._apps:
                    cred = credentials.Certificate(p)
                    firebase_admin.initialize_app(cred)
                firestore_db = firestore.client()
                logging.info(f"Connected to Firebase via {p}")
                return True
            except Exception as e:
                logging.error(f"Firebase auth failed: {e}")
    return False

try_connect_firebase()

# --- কনভার্সেশন স্টেটস ---
(
    UPLOAD_FIREBASE,
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
) = range(1, 22)

def is_admin(user_id: int) -> bool:
    if int(user_id) == int(SUPER_ADMIN_ID):
        return True
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT val FROM settings WHERE key=?", (f"admin_{user_id}",))
    row = c.fetchone()
    conn.close()
    return bool(row)

MENU_BUTTON_REGEX = r"^(🛍️ Buy Product|👤 My Profile|💳 Deposit|🏷️ Get Code|💬 Support|👑 Tutorial|👑 Admin Panel|💼 Product Management|📦 Add Stock|📊 Live Stock|👥 User Management|🔔 Deposit Requests|📜 Deposit History|📢 Broadcast|🏷️ Voucher Management|🛠️ Support Setup|💳 Payment Settings|🔑 Admin Management|🤝 Reseller Management|📽️ Tutorial Setup|👑 Force Join Setup|⚙️ Setup Firebase|🔙 User Menu)$"

# --- কীবোর্ড মেনু ---
def get_user_menu(is_adm=False):
    kb = [
        [KeyboardButton("🛍️ Buy Product")],
        [KeyboardButton("👤 My Profile"), KeyboardButton("💳 Deposit")],
        [KeyboardButton("🏷️ Get Code"), KeyboardButton("💬 Support")],
        [KeyboardButton("👑 Tutorial")],
    ]
    if is_adm:
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
    adm = is_admin(user.id)

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, name, username) VALUES (?, ?, ?)", 
              (user.id, user.full_name, user.username or "None"))
    c.execute("UPDATE users SET name=?, username=? WHERE user_id=?", (user.full_name, user.username or "None", user.id))
    conn.commit()
    conn.close()

    welcome_msg = (
        f"👋 *Welcome, {user.first_name}!*\n\n"
        f"Select an option from the menu below to start shopping or managing your account."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_user_menu(adm))

# --- PROFILE ---
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    conn.close()

    bal = u["balance"] if u else 0.0
    usd = bal / 125.0

    card = (
        "👤 *My Profile*\n\n"
        f"👤 Name     : {update.effective_user.full_name}\n"
        f"🆔 User ID  : `{user_id}`\n"
        f"💲 Balance  : *{bal:.2f} BDT* / {usd:.4f} USDT\n"
        f"⏳ Status   : {'🚫 Banned' if u and u['is_banned'] else '✅ Active'}\n"
        f"───────────────────────────"
    )
    await update.message.reply_text(card, parse_mode="Markdown")

# --- SUPPORT & TUTORIAL ---
async def user_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT val FROM settings WHERE key='support_link'")
    link = c.fetchone()["val"]
    conn.close()

    msg = "🗣️ *Our Support Team*\n\nClick the button below to reach our official support directly:"
    kb = [[InlineKeyboardButton("🗣️ Contact Admin", url=link)]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def user_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT val FROM settings WHERE key='tutorial_link'")
    link = c.fetchone()["val"]
    conn.close()
    await update.message.reply_text(f"👑 *Tutorial Video:*\n👉 {link}", parse_mode="Markdown")

# --- FIREBASE SETUP VIA TELEGRAM ---
async def ask_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text("📁 আপনার Firebase-এর `.json` ফাইলটি ডকুমেন্ট হিসেবে সেন্ড করুন (বা /cancel চাপুন):")
    return UPLOAD_FIREBASE

async def save_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".json"):
        await update.message.reply_text("❌ এটি ভ্যালিড JSON ফাইল নয়! আবার পাঠান:")
        return UPLOAD_FIREBASE

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    try:
        json.loads(file_bytes.decode("utf-8"))
        with open(LOCAL_KEY_PATH, "wb") as f:
            f.write(file_bytes)

        if try_connect_firebase():
            await update.message.reply_text("✅ *Firebase সফলভাবে যুক্ত হয়েছে এবং চালু আছে!*", parse_mode="Markdown", reply_markup=get_admin_menu())
        else:
            await update.message.reply_text("⚠️ ফাইল সংরক্ষিত হয়েছে তবে Firebase রিফ্রেশ ব্যর্থ হয়েছে।")
    except Exception as e:
        await update.message.reply_text(f"❌ এরর: `{e}`", parse_mode="Markdown")

    return ConversationHandler.END

# --- DEPOSIT (SS / TRXID) ---
async def user_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key, val FROM settings")
    settings = dict(c.fetchall())
    conn.close()

    kb = [
        [InlineKeyboardButton("💳 bKash", callback_data="paymeth_bkash"), InlineKeyboardButton("💳 Nagad", callback_data="paymeth_nagad")],
        [InlineKeyboardButton("💳 Rocket", callback_data="paymeth_rocket"), InlineKeyboardButton("💳 Binance", callback_data="paymeth_binance")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    msg = (
        "💳 *Deposit Options*\n\n"
        f"• bKash: `{settings.get('bkash')}`\n"
        f"• Nagad: `{settings.get('nagad')}`\n"
        f"• Rocket: `{settings.get('rocket')}`\n"
        f"• Binance: `{settings.get('binance')}`\n\n"
        "পেমেন্ট মেথড সিলেক্ট করুন:"
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_method_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("paymeth_", "")
    context.user_data["dep_method"] = method

    msg = f"💳 *Selected: {method.upper()}*\n\nআপনি কত টাকা পাঠিয়েছেন তা লিখুন (in BDT):"
    kb = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        amt = float(text)
        if amt <= 0:
            raise ValueError()
        context.user_data["dep_amount"] = amt
    except Exception:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন (যেমন: 100) অথবা /cancel চাপুন:")
        return DEPOSIT_AMOUNT

    await update.message.reply_text(
        "📸 এবার পেমেন্টের *Transaction ID (TrxID)* লিখে দিন অথবা পেমেন্টের *Screenshot (SS)* সেন্ড করুন:",
        parse_mode="Markdown"
    )
    return DEPOSIT_PROOF

async def deposit_proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    amt = context.user_data.get("dep_amount")
    method = context.user_data.get("dep_method")
    photo_file_id = None
    trx_text = "N/A"

    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        trx_text = update.message.caption or "Screenshot Attached"
    elif update.message.text:
        trx_text = update.message.text.strip()

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO deposit_requests (user_id, amount, method, proof, photo_id) VALUES (?, ?, ?, ?, ?)",
              (uid, amt, method, trx_text, photo_file_id))
    req_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{req_id}"),
           InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{req_id}")]]

    caption = (
        f"🔔 *NEW DEPOSIT REQUEST*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• User ID : `{uid}`\n"
        f"• Amount  : *{amt:.2f} BDT*\n"
        f"• Method  : {method.upper()}\n"
        f"• Proof   : `{trx_text}`"
    )
    try:
        if photo_file_id:
            await context.bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=photo_file_id, caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logging.error(f"Error alerting admin: {e}")

    await update.message.reply_text("✅ *ডিপোজিট রিকোয়েস্ট জমা হয়েছে!* অ্যাডমিন অ্যাপ্রুভ করলে ব্যালেন্স যোগ হবে।", parse_mode="Markdown")
    return ConversationHandler.END

# --- STORE (DYNAMIC & QUANTITY COUNTER) ---
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT category FROM products")
    cats = [row["category"] for row in c.fetchall()]
    conn.close()

    if not cats:
        msg = "🛍️ *দোকানটি বর্তমানে খালি!*\nকোনো প্রোডাক্ট যোগ করা হয়নি।"
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
        return

    buttons = []
    row = []
    for cat in cats:
        icon = "🌐" if "Proxy" in cat else "🛡️" if "VPN" in cat else "✉️"
        row.append(InlineKeyboardButton(f"{icon} {cat}", callback_data=f"buycat_{cat}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")])

    if update.callback_query:
        await update.callback_query.edit_message_text("🛒 *Buy Products*\n\nSelect a category:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    else:
        await update.message.reply_text("🛒 *Buy Products*\n\nSelect a category:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def handle_buy_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("buycat_", "")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, price FROM products WHERE category=?", (category,))
    prods = c.fetchall()
    conn.close()

    if not prods:
        await query.edit_message_text(f"❌ No products under *{category}*.", parse_mode="Markdown")
        return

    buttons = []
    for p in prods:
        buttons.append([InlineKeyboardButton(f"🔹 {p['name']} ❯ {p['price']:.0f} BDT", callback_data=f"selpkg_{p['id']}")])
    buttons.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="back_to_cats")])

    await query.edit_message_text(f"🛒 *Category: {category}*\n\nSelect a product:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

def build_purchase_summary_kb(qty: int, prod_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"qty_dec_{prod_id}_{qty}"),
            InlineKeyboardButton(f"{qty}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"qty_inc_{prod_id}_{qty}")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_to_cats"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")
        ],
        [InlineKeyboardButton("✅ Confirm", callback_data=f"buy_confirm_{prod_id}_{qty}")]
    ])

async def show_purchase_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = int(query.data.replace("selpkg_", ""))

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id=?", (prod_id,))
    prod = c.fetchone()
    conn.close()

    if not prod:
        await query.edit_message_text("❌ Product not found.")
        return

    qty = 1
    total_price = prod["price"] * qty

    summary_text = (
        "🧾 *PURCHASE SUMMARY*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 *Category:* {prod['category']}\n"
        f"🔹 *Package:* {prod['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Quantity:* {qty}\n"
        f"💲 *Rate:* {prod['price']:.2f} BDT\n"
        f"🛒 *Total Price:* {total_price:.2f} BDT"
    )
    await query.edit_message_text(summary_text, reply_markup=build_purchase_summary_kb(qty, prod_id), parse_mode="Markdown")

async def update_quantity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]
    prod_id = int(parts[2])
    qty = int(parts[3])

    if action == "inc":
        qty += 1
    elif action == "dec" and qty > 1:
        qty -= 1

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id=?", (prod_id,))
    prod = c.fetchone()
    conn.close()

    total_price = prod["price"] * qty

    summary_text = (
        "🧾 *PURCHASE SUMMARY*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 *Category:* {prod['category']}\n"
        f"🔹 *Package:* {prod['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Quantity:* {qty}\n"
        f"💲 *Rate:* {prod['price']:.2f} BDT\n"
        f"🛒 *Total Price:* {total_price:.2f} BDT"
    )
    await query.edit_message_text(summary_text, reply_markup=build_purchase_summary_kb(qty, prod_id), parse_mode="Markdown")

async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    _, _, prod_id_s, qty_str = query.data.split("_")
    prod_id = int(prod_id_s)
    qty = int(qty_str)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    c.execute("SELECT * FROM products WHERE id=?", (prod_id,))
    prod = c.fetchone()

    if not prod:
        conn.close()
        await query.answer("❌ পণ্যটি পাওয়া যায়নি!", show_alert=True)
        return

    price = prod["reseller_price"] if user and user["is_reseller"] else prod["price"]
    total = price * qty

    if not user or user["balance"] < total:
        conn.close()
        await query.answer("❌ পর্যাপ্ত ব্যালেন্স নেই! ডিপোজিট করুন।", show_alert=True)
        return

    c.execute("SELECT id, data FROM stocks WHERE product_id=? LIMIT ?", (prod_id, qty))
    stock_rows = c.fetchall()

    if len(stock_rows) < qty:
        conn.close()
        await query.answer(f"❌ পর্যাপ্ত স্টক নেই! অবশিষ্ট আছে: {len(stock_rows)}", show_alert=True)
        return

    stock_ids = [s["id"] for s in stock_rows]
    delivered = [s["data"] for s in stock_rows]

    c.execute(f"DELETE FROM stocks WHERE id IN ({','.join(['?']*len(stock_ids))})", stock_ids)
    c.execute("UPDATE users SET balance = balance - ?, orders = orders + ? WHERE user_id=?", (total, qty, user_id))
    conn.commit()

    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    rem_bal = c.fetchone()["balance"]
    conn.close()

    formatted_creds = []
    for item in delivered:
        if ":" in item:
            pts = item.split(":")
            if len(pts) >= 4:
                formatted_creds.append(f"*Host:* `{pts[0]}` | *Port:* `{pts[1]}`\n*Username ❯* `{pts[2]}`\n*Password ❯* `{pts[3]}`")
            elif len(pts) == 2:
                formatted_creds.append(f"*Username ❯* `{pts[0]}`\n*Password ❯* `{pts[1]}`")
            else:
                formatted_creds.append(f"`{item}`")
        else:
            formatted_creds.append(f"`{item}`")

    receipt = (
        f"🎉 *{prod['category']} purchase successful!* ✅\n\n"
        f"🔹 *Product:* {prod['name']}\n"
        f"💲 *Remaining Balance:* {rem_bal:.2f} BDT\n\n"
        f"⬇️ *Your Credentials:*\n\n"
        f"{'\n\n'.join(formatted_creds)}\n\n"
        f"🔥 _Thank you for shopping with us!_"
    )
    await query.edit_message_text(receipt, parse_mode="Markdown")

# --- BROADCAST (VOICE / TEXT / PHOTO) ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📢 ব্রডকাস্ট মেসেজ, ভয়েস অথবা ফটো সেন্ড করুন (অথবা /cancel):")
    return BROADCAST_RECEIVE

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    status_msg = await update.message.reply_text("🚀 Broadcasting...")
    success, failed = 0, 0

    for u in users:
        uid = u["user_id"]
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

    await status_msg.edit_text(f"📢 *Broadcast Report:*\n\n✅ Delivered: `{success}`\n❌ Failed: `{failed}`", parse_mode="Markdown")
    return ConversationHandler.END

# --- ADMIN PANEL & LIVE STOCK ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("👑 *Admin Control Panel*", reply_markup=get_admin_menu(), parse_mode="Markdown")

async def live_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT p.id, p.name, p.price, p.category, COUNT(s.id) as stock_count
        FROM products p
        LEFT JOIN stocks s ON p.id = s.product_id
        GROUP BY p.id
    """)
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("🌐 *Live Stock*\n\nকোনো প্রোডাক্ট এখনো যোগ করা হয়নি।", parse_mode="Markdown")
        return

    msg = "🌐 *Live Stock Feed*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for r in rows:
        msg += f"📦 *{r['name']}* | `{r['price']:.0f}৳`\n• Category: {r['category']} | Stock: `{r['stock_count']}`\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- ADD STOCK ---
async def add_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM products")
    prods = c.fetchall()
    conn.close()

    if not prods:
        await update.message.reply_text("❌ আগে প্রোডাক্ট অ্যাড করুন, তারপর স্টক আপলোড করতে পারবেন।")
        return

    buttons = [[InlineKeyboardButton(p["name"], callback_data=f"upstock_{p['id']}")] for p in prods]
    await update.message.reply_text("🗂️ কোন প্রোডাক্টে স্টক অ্যাড করবেন তা বেছে নিন:", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_prepare_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = int(query.data.replace("upstock_", ""))
    context.user_data["upload_prod_id"] = prod_id

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM products WHERE id=?", (prod_id,))
    prod_name = c.fetchone()["name"]
    conn.close()

    msg = (
        f"🗂️ *Upload Stock for:* `{prod_name}`\n\n"
        "Send an *Excel (.xlsx)* or *Text (.txt)* file:\n\n"
        "📌 *Supported Formats:*\n"
        "✏️ *TXT File:* `Host:Port:Username:Password`\n"
        "🧪 *Excel File:* Col A=Host, B=Port, C=User, D=Pass"
    )
    await query.edit_message_text(msg, parse_mode="Markdown")
    return UPLOAD_STOCK

async def process_stock_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    prod_id = context.user_data.get("upload_prod_id")
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
                entries.append(":".join(str(c).strip() for c in row[:4] if c is not None))

    if entries:
        conn = get_db()
        c = conn.cursor()
        c.executemany("INSERT INTO stocks (product_id, data) VALUES (?, ?)", [(prod_id, item) for item in entries])
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ সফলভাবে `{len(entries)}` টি স্টক যুক্ত হয়েছে!", parse_mode="Markdown", reply_markup=get_admin_menu())
    else:
        await update.message.reply_text("❌ ফাইল থেকে কোনো ডাটা পড়া সম্ভব হয়নি।")
    return ConversationHandler.END

# --- PRODUCT MANAGEMENT (ADD / PRICE / DELETE / CLEAR) ---
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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

    conn = get_db()
    c = conn.cursor()

    if act == "add":
        conn.close()
        await query.edit_message_text("ক্যাটাগরির নাম লিখুন (যেমন: Proxy, VPN, Mail):")
        return ADD_PROD_CAT
    elif act == "delprod":
        c.execute("SELECT id, name FROM products")
        prods = c.fetchall()
        conn.close()
        if not prods:
            await query.edit_message_text("❌ কোনো প্রোডাক্ট নেই।")
            return
        kb = [[InlineKeyboardButton(f"❌ {p['name']}", callback_data=f"delp_{p['id']}")] for p in prods]
        kb.append([InlineKeyboardButton("🔙 Cancel", callback_data="cancel_action")])
        await query.edit_message_text("কোন প্রোডাক্টটি ডিলিট করতে চান?", reply_markup=InlineKeyboardMarkup(kb))
    elif act == "delstock":
        c.execute("SELECT id, name FROM products")
        prods = c.fetchall()
        conn.close()
        kb = [[InlineKeyboardButton(f"🧨 Empty {p['name']}", callback_data=f"clearstock_{p['id']}")] for p in prods]
        kb.append([InlineKeyboardButton("🔙 Cancel", callback_data="cancel_action")])
        await query.edit_message_text("কার সমস্ত স্টক খালি করবেন?", reply_markup=InlineKeyboardMarkup(kb))
    elif act == "chprice":
        c.execute("SELECT id, name FROM products")
        prods = c.fetchall()
        conn.close()
        kb = [[InlineKeyboardButton(f"✏️ {p['name']}", callback_data=f"chpr_{p['id']}")] for p in prods]
        kb.append([InlineKeyboardButton("🔙 Cancel", callback_data="cancel_action")])
        await query.edit_message_text("কোন প্রোডাক্টের দাম পাল্টাবেন?", reply_markup=InlineKeyboardMarkup(kb))

async def save_add_prod_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cat"] = update.message.text.strip()
    await update.message.reply_text("প্রোডাক্টের নাম লিখুন (যেমন: 711 PROXY 1 GB):")
    return ADD_PROD_NAME

async def save_add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("সাধারণ মূল্য এবং রিসেলার মূল্য স্পেস দিয়ে লিখুন (যেমন: `70 65`):", parse_mode="Markdown")
    return ADD_PROD_PRICE

async def save_add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন (যেমন: `70 65`):")
        return ADD_PROD_PRICE

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO products (category, name, price, reseller_price) VALUES (?, ?, ?, ?)",
              (context.user_data.get("new_cat"), context.user_data.get("new_name"), price, reseller))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ প্রোডাক্ট সফলভাবে তৈরি এবং লিস্ট করা হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def delete_single_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.replace("delp_", ""))
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE product_id=?", (pid,))
    c.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ প্রোডাক্ট এবং তার সমস্ত স্টক ডিলিট করা হয়েছে!")

async def clear_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.replace("clearstock_", ""))
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE product_id=?", (pid,))
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ সব স্টক ডিলিট করা হয়েছে!")

async def select_prod_for_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["ch_prod_id"] = int(query.data.replace("chpr_", ""))
    await query.edit_message_text("নতুন রেগুলার ও রিসেলার মূল্য দিন (যেমন: `65 60`):", parse_mode="Markdown")
    return CHANGE_PRICE_VAL

async def save_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ সঠিক সংখ্যা দিন (যেমন: `65 60`):")
        return CHANGE_PRICE_VAL

    pid = context.user_data.get("ch_prod_id")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE products SET price=?, reseller_price=? WHERE id=?", (price, reseller, pid))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ মূল্য আপডেট করা হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- USER MANAGEMENT (SEARCH / BAN / BALANCE / MSG) ---
async def user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("👥 ইউজারের টেলিগ্রাম ID বা Username দিন (যেমন: 7072296433):")
    return FIND_USER

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().replace("@", "")
    conn = get_db()
    c = conn.cursor()

    if query.isdigit():
        c.execute("SELECT * FROM users WHERE user_id=?", (int(query),))
    else:
        c.execute("SELECT * FROM users WHERE username=?", (query,))
    u = c.fetchone()
    conn.close()

    if not u:
        await update.message.reply_text("❌ ইউজার খুঁজে পাওয়া যায়নি।")
        return ConversationHandler.END

    target_id = u["user_id"]
    context.user_data["target_uid"] = target_id
    balance = u["balance"]
    usd = balance / 125.0
    status = "Banned" if u["is_banned"] else "Active"

    card = (
        "╔═══════════════════════════╗\n"
        "      👥  *MANAGE USER*     \n"
        "╚═══════════════════════════╝\n"
        f"• *Name:* {u['name']}\n"
        f"• *ID:* `{target_id}`\n"
        f"• *Username:* @{u['username']}\n"
        f"• *Balance:* `{balance:.2f} BDT` (~${usd:.2f} USD)\n"
        f"• *Orders:* `{u['orders']}`\n"
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
    context.user_data["action_uid"] = int(uid)

    if action == "ban":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT is_banned FROM users WHERE user_id=?", (int(uid),))
        row = c.fetchone()
        curr = row["is_banned"] if row else 0
        c.execute("UPDATE users SET is_banned=? WHERE user_id=?", (0 if curr else 1, int(uid)))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ User ID `{uid}` Ban Status: `{bool(not curr)}`", parse_mode="Markdown")
        return ConversationHandler.END
    elif action in ["add", "cut"]:
        context.user_data["bal_op"] = action
        await query.edit_message_text("টাকার পরিমাণ লিখুন (in BDT):")
        return USER_ACTION_AMOUNT
    elif action == "msg":
        await query.edit_message_text("ইউজারকে পাঠানো বার্তাটি লিখুন:")
        return USER_SEND_MSG

async def apply_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন:")
        return USER_ACTION_AMOUNT

    uid = context.user_data.get("action_uid")
    op = context.user_data.get("bal_op")
    delta = amt if op == "add" else -amt

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, uid))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ User `{uid}` এর ব্যালেন্সে `{delta:+.2f} BDT` আপডেট হয়েছে।", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def send_user_direct_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("action_uid")
    msg_text = update.message.text
    try:
        await context.bot.send_message(chat_id=uid, text=f"💬 *Message from Admin:*\n\n{msg_text}", parse_mode="Markdown")
        await update.message.reply_text("✅ বার্তা সফলভাবে পাঠানো হয়েছে!", reply_markup=get_admin_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ পাঠানো যায়নি: {e}")
    return ConversationHandler.END

# --- PAYMENT SETTINGS ---
async def payment_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key, val FROM settings")
    data = dict(c.fetchall())
    conn.close()
    rate = data.get("dollar_rate", "125.0")

    keyboard = [
        [InlineKeyboardButton("Edit bKash Number", callback_data="payedit_bkash")],
        [InlineKeyboardButton("Edit Nagad Number", callback_data="payedit_nagad")],
        [InlineKeyboardButton("Edit Rocket Number", callback_data="payedit_rocket")],
        [InlineKeyboardButton("Edit Binance Pay ID", callback_data="payedit_binance")],
        [InlineKeyboardButton(f"Edit Dollar Rate (Current: {rate} BDT)", callback_data="payedit_dollar_rate")],
    ]
    await update.message.reply_text("💳 *Select Payment Setting to Update:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_payment_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("payedit_", "")
    context.user_data["editing_pay_field"] = field
    await query.edit_message_text(f"নতুন মান লিখুন for `{field}`:")
    return EDIT_PAYMENT_VALUE

async def save_payment_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    field = context.user_data.get("editing_pay_field")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES (?, ?)", (field, val))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ `{field}` আপডেট হয়েছে!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- VOUCHER MANAGEMENT (REDEEM / CREATE) ---
async def get_code_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏷️ *Enter your Voucher Code:*", parse_mode="Markdown")
    return REDEEM_VOUCHER

async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM vouchers WHERE code=?", (code,))
    v = c.fetchone()

    if not v:
        conn.close()
        await update.message.reply_text("❌ ভুল বা অবৈধ ভাউচার কোড।")
        return ConversationHandler.END

    if v["used"]:
        conn.close()
        await update.message.reply_text("❌ এই ভাউচার কোডটি ইতোমধ্যে ব্যবহার করা হয়েছে।")
        return ConversationHandler.END

    amt = v["amount"]
    c.execute("UPDATE vouchers SET used=1 WHERE code=?", (code,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"🎉 *অভিনন্দন!* `{amt:.2f} BDT` আপনার ব্যালেন্সে যোগ হয়েছে।", parse_mode="Markdown")
    return ConversationHandler.END

async def voucher_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("নতুন ভাউচার কোড দিন (যেমন: `OFFER50`):")
    return ADD_VOUCHER_CODE

async def get_v_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_v_code"] = update.message.text.strip().upper()
    await update.message.reply_text("রিওয়ার্ডের টাকার পরিমাণ লিখুন (in BDT):")
    return ADD_VOUCHER_BAL

async def get_v_bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ সংখ্যা লিখুন:")
        return ADD_VOUCHER_BAL

    code = context.user_data.get("new_v_code")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO vouchers (code, amount, used) VALUES (?, ?, 0)", (code, amt))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ ভাউচার `{code}` তৈরি হয়েছে ({amt:.2f} BDT)!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ADMIN DELEGATION ---
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
        await query.edit_message_text("নতুন অ্যাডমিনের Telegram Numeric ID দিন:")
        return ADD_ADMIN_ID
    else:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT key FROM settings WHERE key LIKE 'admin_%'")
        admins = c.fetchall()
        conn.close()
        kb = [[InlineKeyboardButton(f"❌ {a['key'].replace('admin_', '')}", callback_data=f"deladm_{a['key']}")] for a in admins]
        await query.edit_message_text("কাকে অ্যাডমিন থেকে রিমুভ করবেন?", reply_markup=InlineKeyboardMarkup(kb))

async def save_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.message.text.strip()
    if not aid.isdigit():
        await update.message.reply_text("❌ শুধুমাত্র সংখ্যা আইডি দিন:")
        return ADD_ADMIN_ID
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES (?, '1')", (f"admin_{aid}",))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ User ID `{aid}` কে অ্যাডমিন করা হয়েছে!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def del_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("deladm_", "")
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ অ্যাডমিন রিমুভ করা হয়েছে!")

# --- RESELLER, SUPPORT, TUTORIAL, FORCE JOIN ---
async def reseller_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("রিসেলার রোল টগল করতে ইউজারের টেলিগ্রাম ID দিন:")
    return RESELLER_UID

async def save_reseller_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text.strip()
    if not uid.isdigit():
        await update.message.reply_text("❌ সঠিক সংখ্যা আইডি দিন।")
        return ConversationHandler.END

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_reseller FROM users WHERE user_id=?", (int(uid),))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ ইউজার পাওয়া যায়নি।")
        return ConversationHandler.END

    status = 0 if row["is_reseller"] else 1
    c.execute("UPDATE users SET is_reseller=? WHERE user_id=?", (status, int(uid)))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ User `{uid}` এর Reseller স্ট্যাটাস: `{'Active' if status else 'Revoked'}`", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("সাপোর্ট লিংক পাঠান (যেমন: `https://t.me/admin`):")
    return SETUP_SUPPORT

async def save_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('support_link', ?)", (link,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ সাপোর্ট লিংক সংরক্ষিত হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("টিউটোরিয়াল ভিডিও লিংক দিন:")
    return SETUP_TUTORIAL

async def save_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('tutorial_link', ?)", (link,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ টিউটোরিয়াল লিংক সংরক্ষিত হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("ফোর্স জয়েন চ্যানেলের ইউজারনেম দিন (যেমন: `@MyChannel`):")
    return SETUP_FORCE_JOIN

async def save_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('force_channel', ?)", (ch,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ ফোর্স জয়েন চ্যানেল আপডেট হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- DEPOSIT APPROVAL / REJECTION & HISTORY ---
async def show_deposit_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM deposit_requests WHERE status='pending'")
    reqs = c.fetchall()
    conn.close()

    if not reqs:
        await update.message.reply_text("✅ কোনো পেন্ডিং ডিপোজিট নেই।")
        return

    for r in reqs:
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{r['id']}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{r['id']}")]]
        card = (
            f"🔔 *PENDING DEPOSIT*\n"
            f"• User ID : `{r['user_id']}`\n"
            f"• Amount  : *{r['amount']:.2f} BDT*\n"
            f"• Method  : {r['method'].upper()}\n"
            f"• Proof   : `{r['proof']}`"
        )
        if r["photo_id"]:
            await context.bot.send_photo(chat_id=update.effective_user.id, photo=r["photo_id"], caption=card, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(card, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def handle_deposit_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act, req_id_s = query.data.split("_")
    req_id = int(req_id_s)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM deposit_requests WHERE id=?", (req_id,))
    r = c.fetchone()

    if not r or r["status"] != "pending":
        conn.close()
        return

    if act == "depapp":
        c.execute("UPDATE deposit_requests SET status='approved' WHERE id=?", (req_id,))
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (r["amount"], r["user_id"]))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(chat_id=r["user_id"], text=f"✅ *Deposit Approved!*\nAmount: *{r['amount']:.0f} BDT*", parse_mode="Markdown")
        except Exception:
            pass
        msg = f"✅ Approved {r['amount']} BDT for `{r['user_id']}`"
    else:
        c.execute("UPDATE deposit_requests SET status='rejected' WHERE id=?", (req_id,))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(chat_id=r["user_id"], text=f"❌ Deposit request of {r['amount']} BDT was rejected.")
        except Exception:
            pass
        msg = f"❌ Rejected deposit for `{r['user_id']}`"

    if query.message.photo:
        await query.edit_message_caption(caption=msg)
    else:
        await query.edit_message_text(msg)

async def deposit_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM deposit_requests ORDER BY id DESC LIMIT 10")
    history = c.fetchall()
    conn.close()

    if not history:
        await update.message.reply_text("হিস্ট্রিতে কোনো তথ্য নেই।")
        return
    msg = "⚙️ *Recent Deposit History:*\n━━━━━━━━━━━━━━━━━━━━\n"
    for h in history:
        msg += f"• `{h['user_id']}` | `{h['amount']} BDT` | {h['method'].upper()} | `{h['status'].upper()}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- CANCEL & NOOP ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action canceled.", reply_markup=get_user_menu(is_admin(update.effective_user.id)))
    return ConversationHandler.END

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Action canceled.")

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# --- MAIN DISPATCHER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ১. Setup Firebase
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⚙️ Setup Firebase$"), ask_firebase_json)],
        states={UPLOAD_FIREBASE: [MessageHandler(filters.Document.ALL, save_firebase_json)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ২. Add Stock
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_prepare_upload, pattern=r"^upstock_")],
        states={UPLOAD_STOCK: [MessageHandler(filters.Document.ALL, process_stock_file)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৩. Deposit
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💳 Deposit$"), user_deposit_start)],
        states={
            DEPOSIT_AMOUNT: [
                CallbackQueryHandler(deposit_method_picked, pattern=r"^paymeth_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), deposit_amount_received)
            ],
            DEPOSIT_PROOF: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), deposit_proof_received)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel_callback, pattern=r"^cancel_action$"),
            MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)
        ],
    ))

    # ৪. Product Management (Add / Price)
    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_add$"),
            CallbackQueryHandler(select_prod_for_price, pattern=r"^chpr_"),
        ],
        states={
            ADD_PROD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_add_prod_cat)],
            ADD_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_add_prod_name)],
            ADD_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_add_prod_price)],
            CHANGE_PRICE_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_new_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৫. Broadcast
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast$"), start_broadcast)],
        states={BROADCAST_RECEIVE: [MessageHandler((filters.TEXT | filters.VOICE | filters.PHOTO) & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৬. Voucher Redeem
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Get Code$"), get_code_prompt)],
        states={REDEEM_VOUCHER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), redeem_code)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৭. Voucher Create
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Voucher Management$"), voucher_management)],
        states={
            ADD_VOUCHER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), get_v_code)],
            ADD_VOUCHER_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), get_v_bal)]
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৮. User Management
    app.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^👥 User Management$"), user_management),
            CallbackQueryHandler(user_actions_callback, pattern=r"^uact_(add|cut|msg)_")
        ],
        states={
            FIND_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), search_user)],
            USER_ACTION_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), apply_user_balance)],
            USER_SEND_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), send_user_direct_msg)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৯. Payment Settings
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_payment_edit, pattern=r"^payedit_")],
        states={EDIT_PAYMENT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_payment_value)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ১০. Add Admin
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_add$")],
        states={ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_new_admin)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ১১. Reseller, Support, Tutorial, Force Join
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🤝 Reseller Management$"), reseller_management)],
        states={RESELLER_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_reseller_toggle)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠️ Support Setup$"), prompt_support_setup)],
        states={SETUP_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_support_setup)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📽️ Tutorial Setup$"), prompt_tutorial_setup)],
        states={SETUP_TUTORIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_tutorial_setup)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👑 Force Join Setup$"), prompt_force_join)],
        states={SETUP_FORCE_JOIN: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_force_join)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # মূল মেনু হ্যান্ডলারসমূহ
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

    # ইনলাইন বাটন কলব্যাকস
    app.add_handler(CallbackQueryHandler(buy_products_menu, pattern=r"^back_to_cats$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern=r"^cancel_action$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(handle_buy_cat, pattern=r"^buycat_"))
    app.add_handler(CallbackQueryHandler(show_purchase_summary, pattern=r"^selpkg_"))
    app.add_handler(CallbackQueryHandler(update_quantity_callback, pattern=r"^qty_(inc|dec)_"))
    app.add_handler(CallbackQueryHandler(confirm_purchase, pattern=r"^buy_confirm_"))
    app.add_handler(CallbackQueryHandler(handle_deposit_decide, pattern=r"^dep(app|rej)_"))
    app.add_handler(CallbackQueryHandler(handle_prodman_actions, pattern=r"^prodman_"))
    app.add_handler(CallbackQueryHandler(delete_single_product, pattern=r"^delp_"))
    app.add_handler(CallbackQueryHandler(clear_product_stock, pattern=r"^clearstock_"))
    app.add_handler(CallbackQueryHandler(del_admin_cb, pattern=r"^deladm_"))
    app.add_handler(CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_del$"))

    logging.info("Bot polling is active...")
    app.run_polling()

if __name__ == "__main__":
    main()