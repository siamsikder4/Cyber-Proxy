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

# --- RENDER WEB SERVICE PORT LISTENER ---
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
BOT_TOKEN = "8868386011:AAGmU_Bm_TNfuaa66wijUBFb5tFuKMCk77c"
SUPER_ADMIN_ID = 8271633124
LOCAL_KEY_PATH = "serviceAccountKey.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- PREMIUM CUSTOM EMOJI CONFIGURATION ---
# আপনার পছন্দের টেলিগ্রাম প্রিমিয়াম ইমোজি আইডিগুলো নিচে বসিয়ে দিন
EMOJI = {
    "sparkles": '<tg-emoji emoji-id="5368324170671202286">✨</tg-emoji>',
    "cart": '<tg-emoji emoji-id="5427168097561845112">🛒</tg-emoji>',
    "crown": '<tg-emoji emoji-id="5427168097561845113">👑</tg-emoji>',
    "shield": '<tg-emoji emoji-id="5427168097561845114">🛡️</tg-emoji>',
    "card": '<tg-emoji emoji-id="5427168097561845115">💳</tg-emoji>',
    "profile": '<tg-emoji emoji-id="5427168097561845116">👤</tg-emoji>',
    "money": '<tg-emoji emoji-id="5427168097561845117">💰</tg-emoji>',
    "verified": '<tg-emoji emoji-id="5427168097561845118">✅</tg-emoji>',
    "cross": '<tg-emoji emoji-id="5427168097561845119">❌</tg-emoji>',
    "fire": '<tg-emoji emoji-id="5427168097561845120">🔥</tg-emoji>',
    "box": '<tg-emoji emoji-id="5427168097561845121">📦</tg-emoji>',
    "bell": '<tg-emoji emoji-id="5427168097561845122">🔔</tg-emoji>',
    "key": '<tg-emoji emoji-id="5427168097561845123">🔑</tg-emoji>',
    "tag": '<tg-emoji emoji-id="5427168097561845124">🏷️</tg-emoji>',
    "gear": '<tg-emoji emoji-id="5427168097561845125">⚙️</tg-emoji>'
}

# --- DATABASE SETUP ---
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
    
    defaults = [
        ('bkash', '01XXXXXXXXX'),
        ('nagad', '01XXXXXXXXX'),
        ('rocket', '01XXXXXXXXX'),
        ('binance', '1266509663'),
        ('dollar_rate', '125.0'),
        ('support_link', 'https://t.me/your_admin'),
        ('tutorial_link', 'https://youtube.com'),
        ('force_channel', '')
    ]
    for key, val in defaults:
        c.execute("INSERT OR IGNORE INTO settings (key, val) VALUES (?, ?)", (key, val))
    conn.commit()
    conn.close()

init_local_db()

# --- FIREBASE HANDLER ---
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

# --- CONVERSATION STATES ---
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

MENU_BUTTON_REGEX = r"^(🛍️ Market Store|👤 My Account|💳 Deposit Balance|🏷️ Redeem Voucher|💬 24/7 Support|👑 Tutorial Guide|⚡ Admin Control|📦 Stock Center|📊 Inventory Matrix|👥 Customer Hub|🔔 Deposit Approvals|📜 Transaction Logs|📢 Announce Broadcast|🏷️ Voucher Studio|🛠️ System Channels|💳 Gateway Setup|🔑 Admin Delegation|🤝 Reseller Suite|⚙️ Cloud Integration|🔙 Main Menu)$"

# --- MENUS ---
def get_user_menu(is_adm=False):
    kb = [
        [KeyboardButton("🛍️ Market Store")],
        [KeyboardButton("👤 My Account"), KeyboardButton("💳 Deposit Balance")],
        [KeyboardButton("🏷️ Redeem Voucher"), KeyboardButton("💬 24/7 Support")],
        [KeyboardButton("👑 Tutorial Guide")],
    ]
    if is_adm:
        kb.append([KeyboardButton("⚡ Admin Control")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_admin_menu():
    kb = [
        [KeyboardButton("📦 Stock Center"), KeyboardButton("📊 Inventory Matrix")],
        [KeyboardButton("👥 Customer Hub"), KeyboardButton("🔔 Deposit Approvals")],
        [KeyboardButton("📢 Announce Broadcast"), KeyboardButton("🏷️ Voucher Studio")],
        [KeyboardButton("💳 Gateway Setup"), KeyboardButton("🔑 Admin Delegation")],
        [KeyboardButton("🤝 Reseller Suite"), KeyboardButton("🛠️ System Channels")],
        [KeyboardButton("📜 Transaction Logs"), KeyboardButton("⚙️ Cloud Integration")],
        [KeyboardButton("🔙 Main Menu")]
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
        f"{EMOJI['sparkles']} <b>Welcome to Exclusive Store, {user.first_name}!</b>\n\n"
        f"{EMOJI['cart']} High-speed proxies, VPN credentials, and instant services.\n"
        f"{EMOJI['shield']} <i>Automated, secure, and fast instant delivery.</i>\n\n"
        f"Select an option below to get started:"
    )
    await update.message.reply_text(welcome_msg, parse_mode="HTML", reply_markup=get_user_menu(adm))

# --- PROFILE ---
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    conn.close()

    bal = u["balance"] if u else 0.0
    orders = u["orders"] if u else 0
    usd = bal / 125.0
    status = f"{EMOJI['cross']} Banned" if u and u['is_banned'] else f"{EMOJI['verified']} Verified Member"

    card = (
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"{EMOJI['profile']} <b>VIP ACCOUNT PROFILE</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>Name :</b> {update.effective_user.full_name}\n"
        f"<b>Account ID :</b> <code>{user_id}</code>\n"
        f"<b>Status :</b> {status}\n"
        f"<b>Role :</b> {'🤝 Reseller VIP' if u and u['is_reseller'] else '👤 Retail Member'}\n\n"
        f"{EMOJI['money']} <b>Available Balance:</b>\n"
        f"↳ <b>{bal:.2f} BDT</b> <i>(~${usd:.2f} USDT)</i>\n"
        f"{EMOJI['box']} <b>Completed Purchases:</b> <code>{orders} Items</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
    )
    await update.message.reply_text(card, parse_mode="HTML")

# --- SUPPORT & TUTORIAL ---
async def user_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT val FROM settings WHERE key='support_link'")
    link = c.fetchone()["val"]
    conn.close()

    msg = (
        f"{EMOJI['crown']} <b>Customer Concierge & Support</b>\n\n"
        f"Need assistance or facing an issue? Our team is live 24/7."
    )
    kb = [[InlineKeyboardButton("💬 Connect with Official Support", url=link)]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def user_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT val FROM settings WHERE key='tutorial_link'")
    link = c.fetchone()["val"]
    conn.close()
    await update.message.reply_text(f"{EMOJI['fire']} <b>Master Video Guide:</b>\n👉 <a href='{link}'>Click here to watch the tutorial</a>", parse_mode="HTML", disable_web_page_preview=True)

# --- DEPOSIT SYSTEM ---
async def user_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key, val FROM settings")
    settings = dict(c.fetchall())
    conn.close()

    kb = [
        [InlineKeyboardButton("💳 bKash Personal", callback_data="paymeth_bkash"), InlineKeyboardButton("💳 Nagad Personal", callback_data="paymeth_nagad")],
        [InlineKeyboardButton("💳 Rocket Personal", callback_data="paymeth_rocket"), InlineKeyboardButton("🪙 Binance Pay (USDT)", callback_data="paymeth_binance")],
        [InlineKeyboardButton("✖ Close", callback_data="cancel_action")]
    ]
    msg = (
        f"{EMOJI['card']} <b>DEPOSIT & INSTANT TOP-UP</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"• <b>bKash:</b> <code>{settings.get('bkash')}</code>\n"
        f"• <b>Nagad:</b> <code>{settings.get('nagad')}</code>\n"
        f"• <b>Rocket:</b> <code>{settings.get('rocket')}</code>\n"
        f"• <b>Binance Pay ID:</b> <code>{settings.get('binance')}</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<i>Select your payment gateway below to proceed:</i>"
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return DEPOSIT_AMOUNT

async def deposit_method_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("paymeth_", "")
    context.user_data["dep_method"] = method

    msg = (
        f"{EMOJI['sparkles']} <b>Selected Gateway: {method.upper()}</b>\n\n"
        f"কত টাকা পাঠিয়েছেন তা সংখ্যায় লিখুন (BDT):"
    )
    kb = [[InlineKeyboardButton("✖ Cancel", callback_data="cancel_action")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return DEPOSIT_AMOUNT

async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        amt = float(text)
        if amt <= 0:
            raise ValueError()
        context.user_data["dep_amount"] = amt
    except Exception:
        await update.message.reply_text(f"{EMOJI['cross']} সঠিক সংখ্যা লিখুন (যেমন: 100) অথবা /cancel চাপুন:")
        return DEPOSIT_AMOUNT

    await update.message.reply_text(
        f"{EMOJI['bell']} <b>ভেরিফিকেশন প্রুফ সেন্ড করুন:</b>\n"
        f"পেমেন্টের <b>Transaction ID (TrxID)</b> লিখুন অথবা একটি <b>Screenshot (SS)</b> সেন্ড করুন:",
        parse_mode="HTML"
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

    kb = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{req_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{req_id}")
    ]]

    caption = (
        f"{EMOJI['bell']} <b>NEW DEPOSIT REQUEST #{req_id}</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"• <b>User ID:</b> <code>{uid}</code>\n"
        f"• <b>Amount:</b> <b>{amt:.2f} BDT</b>\n"
        f"• <b>Method:</b> {method.upper()}\n"
        f"• <b>Proof:</b> <code>{trx_text}</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
    )
    try:
        if photo_file_id:
            await context.bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=photo_file_id, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logging.error(f"Error alerting admin: {e}")

    await update.message.reply_text(
        f"{EMOJI['verified']} <b>ডিপোজিট রিকোয়েস্ট সফলভাবে জমা হয়েছে!</b>\n"
        f"অ্যাডমিন ভেরিফাই করলেই আপনার ব্যালেন্সে স্বয়ংক্রিয়ভাবে ফান্ড যোগ হয়ে যাবে।",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# --- STORE (CATEGORIES / QUANTITY / CHECKOUT) ---
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT category FROM products")
    cats = [row["category"] for row in c.fetchall()]
    conn.close()

    if not cats:
        msg = f"{EMOJI['box']} <b>স্টোর বর্তমানে খালি!</b>\nকোনো পণ্য এখনো তালিকাভুক্ত করা হয়নি।"
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    buttons = []
    row = []
    for cat in cats:
        icon = "🌐" if "Proxy" in cat else "🛡️" if "VPN" in cat else "⚡"
        row.append(InlineKeyboardButton(f"{icon} {cat}", callback_data=f"buycat_{cat}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✖ Close Window", callback_data="cancel_action")])

    text = (
        f"{EMOJI['cart']} <b>EXCLUSIVE PRODUCT CATALOG</b>\n\n"
        f"অনুগ্রহ করে আপনার প্রয়োজনীয় ক্যাটাগরি বেছে নিন:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def handle_buy_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("buycat_", "")

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT p.id, p.name, p.price, COUNT(s.id) as stock_cnt
        FROM products p
        LEFT JOIN stocks s ON p.id = s.product_id
        WHERE p.category=?
        GROUP BY p.id
    """, (category,))
    prods = c.fetchall()
    conn.close()

    if not prods:
        await query.edit_message_text(f"{EMOJI['cross']} No products under <b>{category}</b>.", parse_mode="HTML")
        return

    buttons = []
    for p in prods:
        buttons.append([InlineKeyboardButton(f"{p['name']} ❯ {p['price']:.0f}৳ [{p['stock_cnt']} left]", callback_data=f"selpkg_{p['id']}")])
    buttons.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="back_to_cats")])

    text = f"{EMOJI['box']} <b>Catalog: {category}</b>\n\nপ্যাকেজ নির্বাচন করুন:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

def build_purchase_summary_kb(qty: int, prod_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"qty_dec_{prod_id}_{qty}"),
            InlineKeyboardButton(f"Count: {qty}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"qty_inc_{prod_id}_{qty}")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_to_cats"),
            InlineKeyboardButton("✖ Cancel", callback_data="cancel_action")
        ],
        [InlineKeyboardButton("💎 Confirm & Purchase", callback_data=f"buy_confirm_{prod_id}_{qty}")]
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
        await query.edit_message_text(f"{EMOJI['cross']} Product not found.")
        return

    qty = 1
    total_price = prod["price"] * qty

    summary_text = (
        f"{EMOJI['sparkles']} <b>CHECKOUT SUMMARY</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"• <b>Category:</b> {prod['category']}\n"
        f"• <b>Package:</b> <code>{prod['name']}</code>\n"
        f"• <b>Unit Rate:</b> {prod['price']:.2f} BDT\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"{EMOJI['cart']} <b>Order Quantity:</b> <code>{qty}</code>\n"
        f"{EMOJI['money']} <b>Total Amount:</b> <b>{total_price:.2f} BDT</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
    )
    await query.edit_message_text(summary_text, reply_markup=build_purchase_summary_kb(qty, prod_id), parse_mode="HTML")

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
        f"{EMOJI['sparkles']} <b>CHECKOUT SUMMARY</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"• <b>Category:</b> {prod['category']}\n"
        f"• <b>Package:</b> <code>{prod['name']}</code>\n"
        f"• <b>Unit Rate:</b> {prod['price']:.2f} BDT\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"{EMOJI['cart']} <b>Order Quantity:</b> <code>{qty}</code>\n"
        f"{EMOJI['money']} <b>Total Amount:</b> <b>{total_price:.2f} BDT</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
    )
    await query.edit_message_text(summary_text, reply_markup=build_purchase_summary_kb(qty, prod_id), parse_mode="HTML")

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
        await query.answer(f"❌ পর্যাপ্ত স্টক নেই! অবশিষ্ট: {len(stock_rows)}", show_alert=True)
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
                formatted_creds.append(
                    f"<b>Host:</b> <code>{pts[0]}</code> | <b>Port:</b> <code>{pts[1]}</code>\n"
                    f"<b>User ❯</b> <code>{pts[2]}</code>\n"
                    f"<b>Pass ❯</b> <code>{pts[3]}</code>"
                )
            elif len(pts) == 2:
                formatted_creds.append(f"<b>User ❯</b> <code>{pts[0]}</code> | <b>Pass ❯</b> <code>{pts[1]}</code>")
            else:
                formatted_creds.append(f"<code>{item}</code>")
        else:
            formatted_creds.append(f"<code>{item}</code>")

    receipt = (
        f"{EMOJI['verified']} <b>DELIVERY DISPATCH CONFIRMED!</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"• <b>Item:</b> {prod['name']}\n"
        f"• <b>Remaining Balance:</b> <code>{rem_bal:.2f} BDT</code>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"{EMOJI['key']} <b>YOUR CREDENTIALS:</b>\n\n"
        f"{'\n\n'.join(formatted_creds)}\n\n"
        f"{EMOJI['fire']} <i>Thank you for choosing our automated store!</i>"
    )
    await query.edit_message_text(receipt, parse_mode="HTML")

# --- BROADCAST SYSTEM ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['bell']} ব্রডকাস্ট মেসেজ, ভয়েস অথবা ফটো সেন্ড করুন (অথবা /cancel):", parse_mode="HTML")
    return BROADCAST_RECEIVE

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    status_msg = await update.message.reply_text("🚀 Broadcasting to audience...")
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

    await status_msg.edit_text(
        f"{EMOJI['verified']} <b>BROADCAST REPORT</b>\n\n"
        f"• Delivered: <code>{success}</code>\n"
        f"• Failed: <code>{failed}</code>",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# --- ADMIN PANEL & LIVE STOCK ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = (
        f"{EMOJI['crown']} <b>EXECUTIVE CONTROL CONSOLE</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"Welcome, Super Admin. Manage services, inventory, and users below:"
    )
    await update.message.reply_text(text, reply_markup=get_admin_menu(), parse_mode="HTML")

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
        await update.message.reply_text(f"{EMOJI['box']} <b>স্টক খালি!</b> কোনো আইটেম পাওয়া যায়নি।", parse_mode="HTML")
        return

    msg = f"{EMOJI['box']} <b>LIVE INVENTORY FEED</b>\n<b>━━━━━━━━━━━━━━━━━━━━</b>\n\n"
    for r in rows:
        msg += f"<b>{r['name']}</b> ❯ <code>{r['price']:.0f} BDT</code>\n↳ Category: <i>{r['category']}</i> | Stock: <b>{r['stock_count']}</b>\n\n"
    await update.message.reply_text(msg, parse_mode="HTML")

# --- STOCK MANAGEMENT ---
async def add_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM products")
    prods = c.fetchall()
    conn.close()

    if not prods:
        await update.message.reply_text(f"{EMOJI['cross']} আগে প্রোডাক্ট অ্যাড করুন, তারপর স্টক আপলোড করতে পারবেন।", parse_mode="HTML")
        return

    buttons = [[InlineKeyboardButton(f"📦 {p['name']}", callback_data=f"upstock_{p['id']}")] for p in prods]
    await update.message.reply_text(f"{EMOJI['box']} কোন প্রোডাক্টে স্টক অ্যাড করবেন বেছে নিন:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

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
        f"{EMOJI['gear']} <b>Upload Stock for:</b> <code>{prod_name}</code>\n\n"
        f"Send an <b>Excel (.xlsx)</b> or <b>Text (.txt)</b> file:\n\n"
        f"• <b>TXT File:</b> <code>Host:Port:User:Pass</code>\n"
        f"• <b>Excel:</b> Col A=Host, B=Port, C=User, D=Pass"
    )
    await query.edit_message_text(msg, parse_mode="HTML")
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
        await update.message.reply_text(f"{EMOJI['verified']} সফলভাবে <code>{len(entries)}</code> টি স্টক ইনসার্ট হয়েছে!", parse_mode="HTML", reply_markup=get_admin_menu())
    else:
        await update.message.reply_text(f"{EMOJI['cross']} ফাইল থেকে কোনো ডাটা পড়া সম্ভব হয়নি।", parse_mode="HTML")
    return ConversationHandler.END

# --- PRODUCT CRUD ---
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    kb = [
        [InlineKeyboardButton("➕ Add New Product", callback_data="prodman_add")],
        [InlineKeyboardButton("💰 Edit Product Price", callback_data="prodman_chprice")],
        [InlineKeyboardButton("🗑️ Remove Product", callback_data="prodman_delprod")],
        [InlineKeyboardButton("🧨 Purge All Stock", callback_data="prodman_delstock")],
    ]
    await update.message.reply_text(f"{EMOJI['gear']} <b>Product Management Suite</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def handle_prodman_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("prodman_", "")

    conn = get_db()
    c = conn.cursor()

    if act == "add":
        conn.close()
        await query.edit_message_text(f"{EMOJI['tag']} ক্যাটাগরির নাম লিখুন (যেমন: Proxy, VPN, Mail):", parse_mode="HTML")
        return ADD_PROD_CAT
    elif act == "delprod":
        c.execute("SELECT id, name FROM products")
        prods = c.fetchall()
        conn.close()
        if not prods:
            await query.edit_message_text(f"{EMOJI['cross']} কোনো প্রোডাক্ট নেই।", parse_mode="HTML")
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
        await query.edit_message_text("কোন প্রোডাক্টের দাম পরিবর্তন করবেন?", reply_markup=InlineKeyboardMarkup(kb))

async def save_add_prod_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_cat"] = update.message.text.strip()
    await update.message.reply_text(f"{EMOJI['box']} প্রোডাক্টের নাম লিখুন (যেমন: 711 PROXY 1 GB):", parse_mode="HTML")
    return ADD_PROD_NAME

async def save_add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text(f"{EMOJI['money']} সাধারণ ও রিসেলার মূল্য স্পেস দিয়ে লিখুন (যেমন: <code>70 65</code>):", parse_mode="HTML")
    return ADD_PROD_PRICE

async def save_add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text(f"{EMOJI['cross']} সঠিক সংখ্যা লিখুন (যেমন: 70 65):", parse_mode="HTML")
        return ADD_PROD_PRICE

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO products (category, name, price, reseller_price) VALUES (?, ?, ?, ?)",
              (context.user_data.get("new_cat"), context.user_data.get("new_name"), price, reseller))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} প্রোডাক্ট সফলভাবে ডাটাবেজে তৈরি হয়েছে!", reply_markup=get_admin_menu(), parse_mode="HTML")
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
    await query.edit_message_text(f"{EMOJI['verified']} প্রোডাক্ট ও তার সব স্টক ডিলিট হয়েছে।", parse_mode="HTML")

async def clear_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.replace("clearstock_", ""))
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE product_id=?", (pid,))
    conn.commit()
    conn.close()
    await query.edit_message_text(f"{EMOJI['verified']} সম্পূর্ণ স্টক খালি করা হয়েছে।", parse_mode="HTML")

async def select_prod_for_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["ch_prod_id"] = int(query.data.replace("chpr_", ""))
    await query.edit_message_text("নতুন রেগুলার ও রিসেলার মূল্য লিখুন (যেমন: <code>65 60</code>):", parse_mode="HTML")
    return CHANGE_PRICE_VAL

async def save_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text(f"{EMOJI['cross']} সঠিক সংখ্যা দিন (যেমন: 65 60):", parse_mode="HTML")
        return CHANGE_PRICE_VAL

    pid = context.user_data.get("ch_prod_id")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE products SET price=?, reseller_price=? WHERE id=?", (price, reseller, pid))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} প্রাইস সফলভাবে আপডেট হয়েছে!", reply_markup=get_admin_menu(), parse_mode="HTML")
    return ConversationHandler.END

# --- USER MANAGEMENT SUITE ---
async def user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['profile']} ইউজারের Telegram Numeric ID বা Username দিন:", parse_mode="HTML")
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
        await update.message.reply_text(f"{EMOJI['cross']} ইউজার খুঁজে পাওয়া যায়নি।", parse_mode="HTML")
        return ConversationHandler.END

    target_id = u["user_id"]
    context.user_data["target_uid"] = target_id
    balance = u["balance"]
    usd = balance / 125.0
    status = f"{EMOJI['cross']} Banned" if u["is_banned"] else f"{EMOJI['verified']} Active"

    card = (
        f"{EMOJI['profile']} <b>USER MANAGEMENT PROFILE</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"• <b>Name:</b> {u['name']}\n"
        f"• <b>User ID:</b> <code>{target_id}</code>\n"
        f"• <b>Username:</b> @{u['username']}\n"
        f"• <b>Balance:</b> <code>{balance:.2f} BDT</code> (~${usd:.2f})\n"
        f"• <b>Orders:</b> <code>{u['orders']}</code>\n"
        f"• <b>Status:</b> {status}\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
    )

    kb = [
        [InlineKeyboardButton("🚫 Toggle Ban", callback_data=f"uact_ban_{target_id}")],
        [InlineKeyboardButton("➕ Add Balance", callback_data=f"uact_add_{target_id}"),
         InlineKeyboardButton("➖ Deduct Balance", callback_data=f"uact_cut_{target_id}")],
        [InlineKeyboardButton("✉️ Direct Message", callback_data=f"uact_msg_{target_id}")]
    ]
    await update.message.reply_text(card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
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
        await query.edit_message_text(f"{EMOJI['verified']} User <code>{uid}</code> Ban Status: <code>{bool(not curr)}</code>", parse_mode="HTML")
        return ConversationHandler.END
    elif action in ["add", "cut"]:
        context.user_data["bal_op"] = action
        await query.edit_message_text(f"{EMOJI['money']} টাকার পরিমাণ লিখুন (BDT):", parse_mode="HTML")
        return USER_ACTION_AMOUNT
    elif action == "msg":
        await query.edit_message_text(f"{EMOJI['sparkles']} ইউজারকে পাঠানো মেসেজটি টাইপ করুন:", parse_mode="HTML")
        return USER_SEND_MSG

async def apply_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(f"{EMOJI['cross']} সঠিক সংখ্যা লিখুন:", parse_mode="HTML")
        return USER_ACTION_AMOUNT

    uid = context.user_data.get("action_uid")
    op = context.user_data.get("bal_op")
    delta = amt if op == "add" else -amt

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, uid))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"{EMOJI['verified']} User <code>{uid}</code> ব্যালেন্স আপডেট: <code>{delta:+.2f} BDT</code>", parse_mode="HTML", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def send_user_direct_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("action_uid")
    msg_text = update.message.text
    try:
        await context.bot.send_message(chat_id=uid, text=f"{EMOJI['bell']} <b>Official Message from Admin:</b>\n\n{msg_text}", parse_mode="HTML")
        await update.message.reply_text(f"{EMOJI['verified']} বার্তা সফলভাবে পৌঁছে দেওয়া হয়েছে!", reply_markup=get_admin_menu(), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"{EMOJI['cross']} পাঠানো যায়নি: {e}", parse_mode="HTML")
    return ConversationHandler.END

# --- GATEWAY SETTINGS ---
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
        [InlineKeyboardButton("📱 bKash Number", callback_data="payedit_bkash"), InlineKeyboardButton("📱 Nagad Number", callback_data="payedit_nagad")],
        [InlineKeyboardButton("📱 Rocket Number", callback_data="payedit_rocket"), InlineKeyboardButton("🪙 Binance Pay ID", callback_data="payedit_binance")],
        [InlineKeyboardButton(f"💵 Dollar Rate: {rate} BDT", callback_data="payedit_dollar_rate")],
    ]
    await update.message.reply_text(f"{EMOJI['card']} <b>Select Gateway Parameter to Edit:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_payment_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("payedit_", "")
    context.user_data["editing_pay_field"] = field
    await query.edit_message_text(f"নতুন মান লিখুন for <code>{field}</code>:", parse_mode="HTML")
    return EDIT_PAYMENT_VALUE

async def save_payment_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    field = context.user_data.get("editing_pay_field")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES (?, ?)", (field, val))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} <code>{field}</code> সফলভাবে আপডেট হয়েছে!", parse_mode="HTML", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- VOUCHER STUDIO ---
async def get_code_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"{EMOJI['tag']} <b>Enter your Gift/Voucher Code:</b>", parse_mode="HTML")
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
        await update.message.reply_text(f"{EMOJI['cross']} অবৈধ বা ভুল ভাউচার কোড!", parse_mode="HTML")
        return ConversationHandler.END

    if v["used"]:
        conn.close()
        await update.message.reply_text(f"{EMOJI['cross']} এই ভাউচার কোডটি ইতোমধ্যে ব্যবহার করা হয়ে গেছে।", parse_mode="HTML")
        return ConversationHandler.END

    amt = v["amount"]
    c.execute("UPDATE vouchers SET used=1 WHERE code=?", (code,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"{EMOJI['sparkles']} <b>অভিনন্দন!</b> <code>{amt:.2f} BDT</code> আপনার একাউন্টে যুক্ত হয়েছে।", parse_mode="HTML")
    return ConversationHandler.END

async def voucher_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['tag']} নতুন ভাউচার কোড টাইপ করুন (যেমন: <code>OFFER50</code>):", parse_mode="HTML")
    return ADD_VOUCHER_CODE

async def get_v_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_v_code"] = update.message.text.strip().upper()
    await update.message.reply_text(f"{EMOJI['money']} ভাউচারের রিওয়ার্ড ব্যালেন্স লিখুন (BDT):", parse_mode="HTML")
    return ADD_VOUCHER_BAL

async def get_v_bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(f"{EMOJI['cross']} সঠিক সংখ্যা লিখুন:", parse_mode="HTML")
        return ADD_VOUCHER_BAL

    code = context.user_data.get("new_v_code")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO vouchers (code, amount, used) VALUES (?, ?, 0)", (code, amt))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"{EMOJI['verified']} ভাউচার <code>{code}</code> তৈরি হয়েছে (মান: {amt:.2f} BDT)!", parse_mode="HTML", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ADMIN DELEGATION ---
async def admin_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if int(update.effective_user.id) != int(SUPER_ADMIN_ID):
        return
    kb = [
        [InlineKeyboardButton("➕ Grant New Admin", callback_data="admin_add")],
        [InlineKeyboardButton("🗑️ Revoke Admin", callback_data="admin_del")]
    ]
    await update.message.reply_text(f"{EMOJI['key']} <b>ADMIN PRIVILEGE CONTROL</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def handle_admin_manage_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("admin_", "")
    if act == "add":
        await query.edit_message_text(f"{EMOJI['profile']} নতুন অ্যাডমিনের Telegram Numeric ID দিন:", parse_mode="HTML")
        return ADD_ADMIN_ID
    else:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT key FROM settings WHERE key LIKE 'admin_%'")
        admins = c.fetchall()
        conn.close()
        kb = [[InlineKeyboardButton(f"❌ {a['key'].replace('admin_', '')}", callback_data=f"deladm_{a['key']}")] for a in admins]
        await query.edit_message_text("কাকে অ্যাডমিন রোল থেকে বাদ দিতে চান?", reply_markup=InlineKeyboardMarkup(kb))

async def save_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.message.text.strip()
    if not aid.isdigit():
        await update.message.reply_text(f"{EMOJI['cross']} শুধুমাত্র সংখ্যা আইডি দিন:", parse_mode="HTML")
        return ADD_ADMIN_ID
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES (?, '1')", (f"admin_{aid}",))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} User <code>{aid}</code> কে সফলভাবে অ্যাডমিন ক্ষমতা দেওয়া হয়েছে!", parse_mode="HTML", reply_markup=get_admin_menu())
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
    await query.edit_message_text(f"{EMOJI['verified']} অ্যাডমিন রোল প্রত্যাহার করা হয়েছে!", parse_mode="HTML")

# --- RESELLER, SUPPORT & CHANNELS ---
async def reseller_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['crown']} রিসেলার স্ট্যাটাস পরিবর্তন করতে ইউজারের ID দিন:", parse_mode="HTML")
    return RESELLER_UID

async def save_reseller_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text.strip()
    if not uid.isdigit():
        await update.message.reply_text(f"{EMOJI['cross']} সঠিক আইডি দিন।", parse_mode="HTML")
        return ConversationHandler.END

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_reseller FROM users WHERE user_id=?", (int(uid),))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text(f"{EMOJI['cross']} ইউজার পাওয়া যায়নি।", parse_mode="HTML")
        return ConversationHandler.END

    status = 0 if row["is_reseller"] else 1
    c.execute("UPDATE users SET is_reseller=? WHERE user_id=?", (status, int(uid)))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"{EMOJI['verified']} User <code>{uid}</code> Reseller স্ট্যাটাস: <b>{'Active' if status else 'Revoked'}</b>", parse_mode="HTML", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['gear']} সাপোর্ট লিংক দিন (যেমন: <code>https://t.me/admin</code>):", parse_mode="HTML")
    return SETUP_SUPPORT

async def save_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('support_link', ?)", (link,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} সাপোর্ট লিংক সেভ হয়েছে!", reply_markup=get_admin_menu(), parse_mode="HTML")
    return ConversationHandler.END

async def prompt_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['fire']} নতুন ভিডিও টিউটোরিয়াল লিংক দিন:", parse_mode="HTML")
    return SETUP_TUTORIAL

async def save_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('tutorial_link', ?)", (link,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} ভিডিও লিংক আপডেট করা হয়েছে!", reply_markup=get_admin_menu(), parse_mode="HTML")
    return ConversationHandler.END

async def prompt_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"{EMOJI['bell']} ফোর্স জয়েন চ্যানেলের নাম দিন (যেমন: <code>@MyChannel</code>):", parse_mode="HTML")
    return SETUP_FORCE_JOIN

async def save_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, val) VALUES ('force_channel', ?)", (ch,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"{EMOJI['verified']} ফোর্স জয়েন চ্যানেল আপডেট করা হয়েছে!", reply_markup=get_admin_menu(), parse_mode="HTML")
    return ConversationHandler.END

# --- DEPOSIT APPROVALS & HISTORY ---
async def show_deposit_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM deposit_requests WHERE status='pending'")
    reqs = c.fetchall()
    conn.close()

    if not reqs:
        await update.message.reply_text(f"{EMOJI['verified']} কোনো পেন্ডিং ডিপোজিট রিকোয়েস্ট নেই।", parse_mode="HTML")
        return

    for r in reqs:
        kb = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{r['id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{r['id']}")
        ]]
        card = (
            f"{EMOJI['bell']} <b>PENDING DEPOSIT #{r['id']}</b>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"• <b>User ID:</b> <code>{r['user_id']}</code>\n"
            f"• <b>Amount:</b> <b>{r['amount']:.2f} BDT</b>\n"
            f"• <b>Gateway:</b> {r['method'].upper()}\n"
            f"• <b>Proof:</b> <code>{r['proof']}</code>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━</b>"
        )
        if r["photo_id"]:
            await context.bot.send_photo(chat_id=update.effective_user.id, photo=r["photo_id"], caption=card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

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
            await context.bot.send_message(
                chat_id=r["user_id"],
                text=f"{EMOJI['verified']} <b>Deposit Approved!</b>\nAmount: <b>{r['amount']:.0f} BDT</b> has been added to your balance.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        msg = f"{EMOJI['verified']} Approved {r['amount']} BDT for <code>{r['user_id']}</code>"
    else:
        c.execute("UPDATE deposit_requests SET status='rejected' WHERE id=?", (req_id,))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(
                chat_id=r["user_id"],
                text=f"{EMOJI['cross']} <b>Deposit Rejected!</b>\nYour request for {r['amount']:.0f} BDT was declined.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        msg = f"{EMOJI['cross']} Rejected deposit for <code>{r['user_id']}</code>"

    if query.message.photo:
        await query.edit_message_caption(caption=msg, parse_mode="HTML")
    else:
        await query.edit_message_text(msg, parse_mode="HTML")

async def deposit_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM deposit_requests ORDER BY id DESC LIMIT 10")
    history = c.fetchall()
    conn.close()

    if not history:
        await update.message.reply_text(f"{EMOJI['box']} কোনো ট্রানজেকশন হিস্ট্রি নেই।", parse_mode="HTML")
        return
    msg = f"{EMOJI['card']} <b>RECENT DEPOSIT LOGS</b>\n<b>━━━━━━━━━━━━━━━━━━━━</b>\n"
    for h in history:
        msg += f"• <code>{h['user_id']}</code> | <b>{h['amount']} BDT</b> | {h['method'].upper()} | <code>{h['status'].upper()}</code>\n"
    await update.message.reply_text(msg, parse_mode="HTML")

# --- FIREBASE SETUP ---
async def ask_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(f"{EMOJI['gear']} আপনার Firebase-এর <code>.json</code> ফাইলটি সেন্ড করুন (অথবা /cancel):", parse_mode="HTML")
    return UPLOAD_FIREBASE

async def save_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".json"):
        await update.message.reply_text(f"{EMOJI['cross']} ভ্যালিড JSON ফাইল নয়! আবার পাঠান:", parse_mode="HTML")
        return UPLOAD_FIREBASE

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    try:
        json.loads(file_bytes.decode("utf-8"))
        with open(LOCAL_KEY_PATH, "wb") as f:
            f.write(file_bytes)

        if try_connect_firebase():
            await update.message.reply_text(f"{EMOJI['verified']} <b>Firebase Integration Active!</b>", parse_mode="HTML", reply_markup=get_admin_menu())
        else:
            await update.message.reply_text("⚠️ ফাইল সংরক্ষিত হয়েছে তবে রিফ্রেশ ব্যর্থ হয়েছে।")
    except Exception as e:
        await update.message.reply_text(f"{EMOJI['cross']} ত্রুটি: <code>{e}</code>", parse_mode="HTML")

    return ConversationHandler.END

# --- CANCEL & NOOP ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action canceled.", reply_markup=get_user_menu(is_admin(update.effective_user.id)))
    return ConversationHandler.END

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"{EMOJI['cross']} Action canceled.", parse_mode="HTML")

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# --- MAIN DISPATCHER ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ১. Setup Firebase
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⚙️ Cloud Integration$"), ask_firebase_json)],
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
        entry_points=[MessageHandler(filters.Regex("^💳 Deposit Balance$"), user_deposit_start)],
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

    # ৪. Product Management
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
        entry_points=[MessageHandler(filters.Regex("^📢 Announce Broadcast$"), start_broadcast)],
        states={BROADCAST_RECEIVE: [MessageHandler((filters.TEXT | filters.VOICE | filters.PHOTO) & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), execute_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৬. Voucher Redeem
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Redeem Voucher$"), get_code_prompt)],
        states={REDEEM_VOUCHER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), redeem_code)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৭. Voucher Studio
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Voucher Studio$"), voucher_management)],
        states={
            ADD_VOUCHER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), get_v_code)],
            ADD_VOUCHER_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), get_v_bal)]
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # ৮. User Management
    app.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^👥 Customer Hub$"), user_management),
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

    # ১১. Reseller, Support, Channels
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🤝 Reseller Suite$"), reseller_management)],
        states={RESELLER_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_reseller_toggle)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠️ System Channels$"), prompt_support_setup)],
        states={SETUP_SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_support_setup)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👑 Tutorial Guide$"), prompt_tutorial_setup)],
        states={SETUP_TUTORIAL: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTON_REGEX), save_tutorial_setup)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex(MENU_BUTTON_REGEX), cancel)],
    ))

    # মূল মেনু হ্যান্ডলার
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ Market Store$"), buy_products_menu))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Account$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^💬 24/7 Support$"), user_support))
    app.add_handler(MessageHandler(filters.Regex("^👑 Tutorial Guide$"), user_tutorial))
    app.add_handler(MessageHandler(filters.Regex("^⚡ Admin Control$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^📦 Stock Center$"), product_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^📊 Inventory Matrix$"), live_stock))
    app.add_handler(MessageHandler(filters.Regex("^🔔 Deposit Approvals$"), show_deposit_requests))
    app.add_handler(MessageHandler(filters.Regex("^📜 Transaction Logs$"), deposit_history))
    app.add_handler(MessageHandler(filters.Regex("^💳 Gateway Setup$"), payment_settings))
    app.add_handler(MessageHandler(filters.Regex("^🔑 Admin Delegation$"), admin_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Main Menu$"), start))

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

    logging.info("Bot polling is active with Premium HTML Engine...")
    app.run_polling()

if __name__ == "__main__":
    main()