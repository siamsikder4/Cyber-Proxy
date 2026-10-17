import os
import io
import json
import logging
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
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # BotFather থেকে পাওয়া টোকেন
SUPER_ADMIN_ID = 123456789                  # আপনার টেলিগ্রাম নিউমেরিক আইডি

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

FIREBASE_KEY_PATH = "serviceAccountKey.json"
db = None

# --- ফায়ারবেস কানেকশন লজিক ---
def load_firebase():
    global db
    if os.path.exists(FIREBASE_KEY_PATH):
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_KEY_PATH)
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            init_firestore_defaults()
            logging.info("Firebase connected successfully!")
            return True
        except Exception as e:
            logging.error(f"Firebase connection error: {e}")
            return False
    return False

def init_firestore_defaults():
    global db
    if not db:
        return
    # পেমেন্ট ডিফল্ট সেটিংস
    settings_ref = db.collection("settings").document("payments")
    if not settings_ref.get().exists:
        settings_ref.set({
            "bkash": "01XXXXXXXXX",
            "nagad": "01XXXXXXXXX",
            "rocket": "01XXXXXXXXX",
            "binance": "12345678",
            "dollar_rate": 120.0
        })
    
    # সাপোর্ট ও টিউটোরিয়াল ডিফল্ট সেটিংস
    misc_ref = db.collection("settings").document("misc")
    if not misc_ref.get().exists:
        misc_ref.set({
            "support_link": "https://t.me/your_support",
            "tutorial_link": "https://youtube.com",
            "force_channel": ""
        })

    # ডিফল্ট ক্যাটাগরি ও প্রোডাক্ট
    prods = db.collection("products").limit(1).get()
    if len(prods) == 0:
        default_items = [
            {"cat": "Proxy~IP", "name": "1GB USA Proxy 1 Month", "price": 75.0, "reseller": 75.0},
            {"cat": "Proxy~IP", "name": "Rapid Proxy 200 MB", "price": 40.0, "reseller": 40.0},
            {"cat": "Proxy~IP", "name": "Owl Proxy 200 MB", "price": 15.0, "reseller": 15.0},
            {"cat": "Hotmail", "name": "Hotmail Fresh Account", "price": 10.0, "reseller": 8.0},
            {"cat": "Outlook", "name": "Outlook Old Account", "price": 12.0, "reseller": 10.0},
            {"cat": "FR_Outlook", "name": "FR Outlook Account", "price": 15.0, "reseller": 12.0},
            {"cat": "VPN", "name": "NordVPN 1 Month", "price": 120.0, "reseller": 100.0},
        ]
        for item in default_items:
            db.collection("products").add(item)

# কনভার্সেশন স্টেটস
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
    DEL_ADMIN_ID,
    SETUP_SUPPORT,
    SETUP_TUTORIAL,
    SETUP_FORCE_JOIN,
    RESELLER_UID
) = range(1, 24)

# --- কীবোর্ড জেনারেটর ---
def get_user_menu(is_admin=False):
    kb = [
        [KeyboardButton("🎟️ Buy Products")],
        [KeyboardButton("🧑‍💼 My Profile"), KeyboardButton("💵 Deposit")],
        [KeyboardButton("🛡️ Get Code"), KeyboardButton("💬 Support")],
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

async def check_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    if db:
        doc = db.collection("admins").document(str(user_id)).get()
        return doc.exists
    return False

# --- START COMMAND ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = await check_admin(user.id)

    if db:
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

    if not db and is_admin:
        await update.message.reply_text(
            "⚠️ *ফায়ারবেস এখনো কনফিগার করা হয়নি!*\n"
            "অ্যাডমিন প্যানেল থেকে *🔥 Setup Firebase*-এ ক্লিক করে আপনার `serviceAccountKey.json` ফাইলটি পাঠান।",
            parse_mode="Markdown",
            reply_markup=get_user_menu(is_admin)
        )
        return

    await update.message.reply_text("✅ মূল মেনু:", reply_markup=get_user_menu(is_admin))

# --- FIREBASE KEY UPLOADER (ADMIN) ---
async def ask_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("📁 অনুগ্রহ করে Firebase-এর `serviceAccountKey.json` ফাইলটি ডকুমেন্ট হিসেবে পাঠান:")
    return UPLOAD_FIREBASE_JSON

async def save_firebase_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".json"):
        await update.message.reply_text("❌ এটি JSON ফাইল নয়। সঠিক ফাইল দিন।")
        return UPLOAD_FIREBASE_JSON

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    try:
        json.loads(file_bytes.decode("utf-8"))
        with open(FIREBASE_KEY_PATH, "wb") as f:
            f.write(file_bytes)
        
        if load_firebase():
            await update.message.reply_text("✅ Firebase সফলভাবে কানেক্ট হয়েছে এবং প্রস্তুত!", reply_markup=get_admin_menu())
        else:
            await update.message.reply_text("❌ ফাইলটি সেভ হয়েছে তবে Firebase অথেনটিকেশনে সমস্যা হচ্ছে।")
    except Exception as e:
        await update.message.reply_text(f"❌ এরর: {e}")
    return ConversationHandler.END

# --- ইউজার প্রোফাইল ও ফিচারস ---
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("❌ ডাটাবেজ অফলাইন।")
        return
    user_id = str(update.effective_user.id)
    data = db.collection("users").document(user_id).get().to_dict() or {}
    balance = data.get("balance", 0.0)
    usd = balance / 120.0

    msg = (
        f"👥 *USER PROFILE*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👑 Name: {data.get('name', 'N/A')}\n"
        f"🆔 ID: `{user_id}`\n"
        f"🌐 Username: @{data.get('username', 'None')}\n"
        f"💵 Balance: {balance:.1f} BDT ({usd:.2f} USD)\n"
        f"🛒 Orders: {data.get('orders', 0)}\n"
        f"💎 Status: {'🚫 Banned' if data.get('is_banned') else '✅ Active'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def user_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = "https://t.me"
    if db:
        misc = db.collection("settings").document("misc").get().to_dict() or {}
        link = misc.get("support_link", link)
    await update.message.reply_text(f"💬 আমাদের সাপোর্ট হেল্পলাইনে যোগাযোগ করতে ক্লিক করুন:\n👉 {link}")

async def user_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = "https://youtube.com"
    if db:
        misc = db.collection("settings").document("misc").get().to_dict() or {}
        link = misc.get("tutorial_link", link)
    await update.message.reply_text(f"👑 টিউটোরিয়াল দেখতে এই লিংকে প্রবেশ করুন:\n👉 {link}")

# --- ইউজার ডিপোজিট সিস্টেম ---
async def user_deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("❌ ডাটাবেজ অফলাইন।")
        return ConversationHandler.END
    
    settings = db.collection("settings").document("payments").get().to_dict() or {}
    kb = [
        [InlineKeyboardButton("Bkash", callback_data="paymeth_bkash"), InlineKeyboardButton("Nagad", callback_data="paymeth_nagad")],
        [InlineKeyboardButton("Rocket", callback_data="paymeth_rocket"), InlineKeyboardButton("Binance (USDT)", callback_data="paymeth_binance")]
    ]
    msg = (
        f"💳 *পেমেন্ট মেথড নির্বাচন করুন:*\n\n"
        f"• বিকাশ (Personal): `{settings.get('bkash')}`\n"
        f"• নগদ (Personal): `{settings.get('nagad')}`\n"
        f"• রকেট (Personal): `{settings.get('rocket')}`\n"
        f"• Binance Pay ID: `{settings.get('binance')}`\n\n"
        f"💵 ডলার রেট: ১ USD = {settings.get('dollar_rate', 120.0)} BDT"
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return DEPOSIT_AMOUNT

async def deposit_method_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("paymeth_", "")
    context.user_data["dep_method"] = method
    await query.edit_message_text(f"আপনি কত টাকা ডিপোজিট করতে চান (Amount in BDT) তা লিখে পাঠান:")
    return DEPOSIT_AMOUNT

async def deposit_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        context.user_data["dep_amount"] = amt
    except ValueError:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন:")
        return DEPOSIT_AMOUNT

    await update.message.reply_text("আপনার পেমেন্টের Transaction ID (TrxID) অথবা প্রুফ লিখে পাঠান:")
    return DEPOSIT_TRX

async def deposit_trx_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trx = update.message.text.strip()
    uid = str(update.effective_user.id)
    amt = context.user_data.get("dep_amount")
    method = context.user_data.get("dep_method")

    req_ref = db.collection("deposit_requests").add({
        "user_id": uid,
        "amount": amt,
        "method": method,
        "trx": trx,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    req_id = req_ref[1].id

    # সুপার অ্যাডমিনকে নোটিফিকেশন প্রদান
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{req_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{req_id}")
        ]
    ]
    try:
        await context.bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=f"🔔 *নতুন ডিপোজিট রিকোয়েস্ট!*\n\n"
                 f"👤 User ID: `{uid}`\n"
                 f"💰 Amount: {amt} BDT\n"
                 f"💳 Method: {method}\n"
                 f"🧾 TrxID: `{trx}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        logging.error(f"Failed to alert admin: {e}")

    await update.message.reply_text(
        "✅ আপনার ডিপোজিট রিকোয়েস্টটি সফলভাবে জমা হয়েছে! অ্যাডমিন চেক করে অনুমোদন করলে ব্যালেন্স যোগ হবে।"
    )
    return ConversationHandler.END

# --- ভাউচার / কোড সিস্টেম ---
async def get_code_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏷️ আপনার ভাউচার কোডটি লিখে পাঠান:")
    return REDEEM_VOUCHER

async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user_id = str(update.effective_user.id)
    if not db:
        await update.message.reply_text("❌ ডাটাবেজ অফলাইন।")
        return ConversationHandler.END

    doc = db.collection("vouchers").document(code).get()
    if not doc.exists:
        await update.message.reply_text("❌ অবৈধ বা ভুল ভাউচার কোড!")
        return ConversationHandler.END

    v_data = doc.to_dict()
    if v_data.get("used"):
        await update.message.reply_text("❌ এই ভাউচার কোডটি ইতিমধ্যে ব্যবহার করা হয়েছে।")
        return ConversationHandler.END

    amount = v_data.get("amount", 0.0)
    doc.reference.update({"used": True, "used_by": user_id})
    db.collection("users").document(user_id).update({"balance": firestore.Increment(amount)})

    await update.message.reply_text(f"🎉 অভিনন্দন! আপনার একাউন্টে {amount:.1f} BDT ব্যালেন্স যুক্ত হয়েছে।")
    return ConversationHandler.END

# --- প্রোডাক্ট ক্রয় ও ক্যাটালগ ---
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📧 Hotmail", callback_data="buycat_Hotmail"),
         InlineKeyboardButton("📧 Outlook", callback_data="buycat_Outlook")],
        [InlineKeyboardButton("📧 FR_Outlook", callback_data="buycat_FR_Outlook"),
         InlineKeyboardButton("🔒 VPN", callback_data="buycat_VPN")],
        [InlineKeyboardButton("🌐 Proxy~IP", callback_data="buycat_Proxy~IP")]
    ]
    await update.message.reply_text("🗂️ প্যাকেজ সিলেক্ট করুন", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_buy_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("buycat_", "")

    if not db:
        await query.edit_message_text("❌ ডাটাবেজ অফলাইন।")
        return

    prods = db.collection("products").where("cat", "==", category).get()
    if not prods:
        await query.edit_message_text(f"❌ {category} ক্যাটাগরিতে কোনো পণ্য নেই।")
        return

    buttons = []
    for p in prods:
        p_data = p.to_dict()
        stock_count = len(p.reference.collection("stocks").get())
        text = f"🌐 {p_data['name']} | {p_data['price']:.1f}৳ | Stock: {stock_count}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"order_{p.id}")])

    await query.edit_message_text(f"Available {category}:", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    prod_id = query.data.replace("order_", "")

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get().to_dict() or {}
    if user_doc.get("is_banned"):
        await query.answer("🚫 আপনার অ্যাকাউন্ট ব্যান করা রয়েছে!", show_alert=True)
        return

    prod_ref = db.collection("products").document(prod_id)
    prod_doc = prod_ref.get().to_dict()
    if not prod_doc:
        await query.answer("❌ পণ্যটি পাওয়া যায়নি!", show_alert=True)
        return

    stock_query = prod_ref.collection("stocks").limit(1).get()
    if not stock_query:
        await query.answer("❌ দুঃখিত, স্টক শেষ!", show_alert=True)
        return

    price = prod_doc["reseller"] if user_doc.get("is_reseller") else prod_doc["price"]
    if user_doc.get("balance", 0.0) < price:
        await query.answer("❌ পর্যাপ্ত ব্যালেন্স নেই! দয়া করে ডিপোজিট করুন।", show_alert=True)
        return

    stock_item = stock_query[0]
    stock_data = stock_item.to_dict().get("data")
    stock_item.reference.delete()

    user_ref.update({
        "balance": firestore.Increment(-price),
        "orders": firestore.Increment(1)
    })

    await query.edit_message_text(
        f"✅ ক্রয় সফল হয়েছে!\n\n"
        f"📦 পণ্য: *{prod_doc['name']}*\n"
        f"💰 কর্তন: *{price:.1f} BDT*\n\n"
        f"🔑 বিবরণ / ডেলিভারি:\n`{stock_data}`",
        parse_mode="Markdown"
    )

# --- অ্যাডমিন প্যানেল এবং ফিচারসমূহ ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("👑 Welcome Admin", reply_markup=get_admin_menu())

async def live_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("❌ Firebase এখনো সেটআপ করা হয়নি!")
        return
    prods = db.collection("products").get()
    msg = "🌐 *Live Stock*\n\n"
    for p in prods:
        d = p.to_dict()
        count = len(p.reference.collection("stocks").get())
        msg += f"📦 *{d['name']}* | Price: {d['price']:.1f}৳\n(Reseller: {d.get('reseller', d['price']):.1f}৳) | Stock: {count}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- বাল্ক স্টক আপলোড (TXT / XLSX) ---
async def add_stock_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    if not db:
        await update.message.reply_text("❌ Firebase সেটআপ নেই!")
        return
    keyboard = [
        [InlineKeyboardButton("📧 Hotmail", callback_data="stockcat_Hotmail"),
         InlineKeyboardButton("📧 Outlook", callback_data="stockcat_Outlook")],
        [InlineKeyboardButton("📧 FR_Outlook", callback_data="stockcat_FR_Outlook"),
         InlineKeyboardButton("🌐 Proxy~IP", callback_data="stockcat_Proxy~IP")]
    ]
    await update.message.reply_text("🗂️ কোন ক্যাটাগরিতে স্টক অ্যাড করবেন?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_stock_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("stockcat_", "")

    prods = db.collection("products").where("cat", "==", category).get()
    buttons = [[InlineKeyboardButton(p.to_dict()["name"], callback_data=f"upstock_{p.id}")] for p in prods]
    await query.edit_message_text(f"পণ্য সিলেক্ট করুন ({category}):", reply_markup=InlineKeyboardMarkup(buttons))

async def handle_prepare_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = query.data.replace("upstock_", "")
    context.user_data["upload_prod_id"] = prod_id

    prod_name = db.collection("products").document(prod_id).get().to_dict().get("name")
    instruction = (
        f"🗂️ *{prod_name}* এর জন্য Excel (.xlsx) অথবা Text (.txt) ফাইলটি পাঠান:\n\n"
        f"📌 *আপলোডের সঠিক ফরম্যাট:*\n"
        f"✏️ *TXT ফাইল হলে:*\n"
        f"`Host:Port:Username:Password` (মাঝে : থাকবে)\n\n"
        f"🧪 *Excel ফাইল হলে:*\n"
        f"• কলাম A = Host\n"
        f"• কলাম B = Port\n"
        f"• কলাম C = Username\n"
        f"• কলাম D = Password"
    )
    await query.edit_message_text(instruction, parse_mode="Markdown")
    return UPLOAD_STOCK

async def process_stock_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    prod_id = context.user_data.get("upload_prod_id")
    if not prod_id or not db:
        await update.message.reply_text("❌ ত্রুটি ঘটেছে।")
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

        await update.message.reply_text(
            f"✅ মোট {len(entries)} টি স্টক সফলভাবে Firebase এ আপলোড করা হয়েছে!",
            reply_markup=get_admin_menu()
        )
    else:
        await update.message.reply_text("❌ ফাইলে কোনো ডাটা পাওয়া যায়নি।")
    return ConversationHandler.END

# --- প্রোডাক্ট ম্যানেজমেন্ট (Add / Delete / Price / Delete Stock) ---
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    kb = [
        [InlineKeyboardButton("👑 Add Normal Product", callback_data="prodman_add"),
         InlineKeyboardButton("🗂️ Add API Product", callback_data="prodman_addapi")],
        [InlineKeyboardButton("💰 Change Price", callback_data="prodman_chprice")],
        [InlineKeyboardButton("❌ Delete Product", callback_data="prodman_delprod")],
        [InlineKeyboardButton("🧨 Delete Product Stock", callback_data="prodman_delstock")],
    ]
    await update.message.reply_text("⚙️ *Product Management:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_prodman_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("prodman_", "")

    if act == "add":
        kb = [
            [InlineKeyboardButton("📧 Hotmail", callback_data="setcat_Hotmail"), InlineKeyboardButton("📧 Outlook", callback_data="setcat_Outlook")],
            [InlineKeyboardButton("📧 FR_Outlook", callback_data="setcat_FR_Outlook"), InlineKeyboardButton("🔒 VPN", callback_data="setcat_VPN")],
            [InlineKeyboardButton("🌐 Proxy~IP", callback_data="setcat_Proxy~IP")]
        ]
        await query.edit_message_text("কোন ক্যাটাগরিতে প্রোডাক্ট অ্যাড করবেন?", reply_markup=InlineKeyboardMarkup(kb))
        return ADD_PROD_CAT

    elif act == "delprod":
        prods = db.collection("products").get()
        kb = [[InlineKeyboardButton(f"❌ {p.to_dict()['name']}", callback_data=f"delp_{p.id}")] for p in prods]
        await query.edit_message_text("❌ কোন প্রোডাক্টটি ডিলিট করবেন?", reply_markup=InlineKeyboardMarkup(kb))

    elif act == "delstock":
        prods = db.collection("products").get()
        kb = [[InlineKeyboardButton(f"🧨 Clear {p.to_dict()['name']}", callback_data=f"clearstock_{p.id}")] for p in prods]
        await query.edit_message_text("🧨 কার সব স্টক খালি করতে চান?", reply_markup=InlineKeyboardMarkup(kb))

    elif act == "chprice":
        prods = db.collection("products").get()
        kb = [[InlineKeyboardButton(f"✏️ {p.to_dict()['name']}", callback_data=f"chpr_{p.id}")] for p in prods]
        await query.edit_message_text("কোন প্রোডাক্টের দাম পরিবর্তন করবেন?", reply_markup=InlineKeyboardMarkup(kb))
        return CHANGE_PRICE_SELECT

async def save_add_prod_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("setcat_", "")
    context.user_data["new_prod_cat"] = cat
    await query.edit_message_text(f"ক্যাটাগরি: {cat}\nএবার প্রোডাক্টের নাম লিখে পাঠান:")
    return ADD_PROD_NAME

async def save_add_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data["new_prod_name"] = name
    await update.message.reply_text("প্রোডাক্টের সাধারণ মূল্য (Price in BDT) ও রিসেলার মূল্য স্পেস দিয়ে লিখুন:\nউদাহরণ: `50 45`")
    return ADD_PROD_PRICE

async def save_add_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ সঠিক ফরম্যাটে সংখ্যা লিখুন (যেমন: 50 45):")
        return ADD_PROD_PRICE

    db.collection("products").add({
        "cat": context.user_data.get("new_prod_cat"),
        "name": context.user_data.get("new_prod_name"),
        "price": price,
        "reseller": reseller
    })
    await update.message.reply_text("✅ নতুন প্রোডাক্ট সফলভাবে যোগ করা হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def delete_single_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("delp_", "")
    db.collection("products").document(pid).delete()
    await query.edit_message_text("✅ প্রোডাক্টটি ডিলিট করা হয়েছে!")

async def clear_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("clearstock_", "")
    stocks = db.collection("products").document(pid).collection("stocks").get()
    batch = db.batch()
    for s in stocks:
        batch.delete(s.reference)
    batch.commit()
    await query.edit_message_text("✅ সব স্টক ডিলিট করা হয়েছে!")

async def select_prod_for_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("chpr_", "")
    context.user_data["ch_prod_id"] = pid
    await query.edit_message_text("নতুন সাধারণ মূল্য ও রিসেলার মূল্য লিখে পাঠান (যেমন: 60 55):")
    return CHANGE_PRICE_VAL

async def save_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        price = float(parts[0])
        reseller = float(parts[1]) if len(parts) > 1 else price
    except Exception:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন:")
        return CHANGE_PRICE_VAL

    pid = context.user_data.get("ch_prod_id")
    db.collection("products").document(pid).update({"price": price, "reseller": reseller})
    await update.message.reply_text("✅ পণ্যের মূল্য আপডেট হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ইউজার ম্যানেজমেন্ট সিস্টেম ---
async def user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("👥 ইউজারের টেলিগ্রাম ID বা Username দিন:")
    return FIND_USER

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().replace("@", "")
    target_user, target_id = None, None

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
        await update.message.reply_text("❌ ইউজার খুঁজে পাওয়া যায়নি।")
        return ConversationHandler.END

    context.user_data["target_uid"] = target_id
    balance = target_user.get("balance", 0.0)
    usd = balance / 120.0
    status = "Banned" if target_user.get("is_banned") else "Active"

    card = (
        f"👥 *USER PROFILE*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👑 Name: {target_user.get('name', 'N/A')}\n"
        f"🆔 ID: `{target_id}`\n"
        f"🌐 Username: @{target_user.get('username', 'None')}\n"
        f"💵 Balance: {balance:.1f} BDT ({usd:.2f} USD)\n"
        f"🛒 Orders: {target_user.get('orders', 0)}\n"
        f"💎 Status: {'🚫' if status == 'Banned' else '✅'} {status}"
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

    if action == "ban":
        ref = db.collection("users").document(uid)
        curr = ref.get().to_dict().get("is_banned", False)
        ref.update({"is_banned": not curr})
        await query.edit_message_text(f"✅ User ID {uid} এর ব্যান স্ট্যাটাস পরিবর্তন হয়েছে: {not curr}")
        return ConversationHandler.END
    elif action in ["add", "cut"]:
        context.user_data["bal_op"] = action
        await query.edit_message_text("টাকার পরিমাণ (Amount in BDT) লিখে পাঠান:")
        return USER_ACTION_AMOUNT
    elif action == "msg":
        await query.edit_message_text(f"ইউজারকে পাঠানোর মেসেজটি লিখে পাঠান:")
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

    db.collection("users").document(uid).update({"balance": firestore.Increment(delta)})
    await update.message.reply_text(f"✅ ইউজার {uid} এর একাউন্টে {amt} BDT {'যুক্ত' if op == 'add' else 'কর্তন'} হয়েছে।", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def send_user_direct_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("action_uid")
    msg_text = update.message.text
    try:
        await context.bot.send_message(chat_id=int(uid), text=f"📩 *অ্যাডমিন থেকে বার্তা:*\n\n{msg_text}", parse_mode="Markdown")
        await update.message.reply_text("✅ মেসেজ সফলভাবে পাঠানো হয়েছে!", reply_markup=get_admin_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ মেসেজ পাঠানো যায়নি: {e}")
    return ConversationHandler.END

# --- ডিপোজিট ম্যানেজমেন্ট (Admin Approve / Reject / History) ---
async def show_deposit_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    reqs = db.collection("deposit_requests").where("status", "==", "pending").get()
    if not reqs:
        await update.message.reply_text("❌ কোনো পেন্ডিং ডিপোজিট নেই।")
        return

    for r in reqs:
        d = r.to_dict()
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"depapp_{r.id}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"deprej_{r.id}")]]
        await update.message.reply_text(
            f"🔔 *পেন্ডিং ডিপোজিট:*\n"
            f"👤 User: `{d['user_id']}`\n"
            f"💰 Amount: {d['amount']} BDT\n"
            f"💳 Method: {d['method']}\n"
            f"🧾 Trx: `{d['trx']}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def handle_deposit_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act, req_id = query.data.split("_")
    ref = db.collection("deposit_requests").document(req_id)
    doc = ref.get()
    if not doc.exists:
        await query.edit_message_text("❌ রিকোয়েস্ট পাওয়া যায়নি।")
        return

    data = doc.to_dict()
    if data["status"] != "pending":
        await query.edit_message_text("⚠️ এটি আগেই প্রসেস করা হয়েছে।")
        return

    if act == "depapp":
        ref.update({"status": "approved"})
        db.collection("users").document(data["user_id"]).update({"balance": firestore.Increment(data["amount"])})
        try:
            await context.bot.send_message(
                chat_id=int(data["user_id"]),
                text=f"✅ আপনার {data['amount']} BDT ডিপোজিট সফলভাবে অনুমোদিত হয়েছে!"
            )
        except Exception:
            pass
        await query.edit_message_text(f"✅ Approved: {data['amount']} BDT for `{data['user_id']}`")
    else:
        ref.update({"status": "rejected"})
        try:
            await context.bot.send_message(
                chat_id=int(data["user_id"]),
                text=f"❌ আপনার {data['amount']} BDT ডিপোজিট বাতিল করা হয়েছে।"
            )
        except Exception:
            pass
        await query.edit_message_text(f"❌ Rejected: {data['amount']} BDT")

async def deposit_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    history = db.collection("deposit_requests").order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).get()
    if not history:
        await update.message.reply_text("হিস্ট্রিতে কোনো তথ্য পাওয়া যায়নি।")
        return
    msg = "⚙️ *সাম্প্রতিক ডিপোজিট হিস্ট্রি:*\n\n"
    for h in history:
        d = h.to_dict()
        msg += f"• `{d['user_id']}` | {d['amount']} BDT | {d['method']} | {d['status'].upper()}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- পেমেন্ট সেটিংস কনফিগারেশন ---
async def payment_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    data = db.collection("settings").document("payments").get().to_dict() or {}
    rate = data.get("dollar_rate", 120.0)

    keyboard = [
        [InlineKeyboardButton("Edit Bkash Number", callback_data="payedit_bkash")],
        [InlineKeyboardButton("Edit Nagad Number", callback_data="payedit_nagad")],
        [InlineKeyboardButton("Edit Rocket Number", callback_data="payedit_rocket")],
        [InlineKeyboardButton("Edit Binance Number", callback_data="payedit_binance")],
        [InlineKeyboardButton(f"Edit Dollar Rate (Current: {rate:.1f} BDT)", callback_data="payedit_dollar_rate")],
    ]
    await update.message.reply_text("⚙️ *কোন পেমেন্ট মেথডের নাম্বার পরিবর্তন করবেন?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_payment_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("payedit_", "")
    context.user_data["editing_pay_field"] = field
    await query.edit_message_text(f"নতুন মান (New Value) লিখে পাঠান:")
    return EDIT_PAYMENT_VALUE

async def save_payment_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    field = context.user_data.get("editing_pay_field")
    if field == "dollar_rate":
        try:
            val = float(val)
        except ValueError:
            await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন:")
            return EDIT_PAYMENT_VALUE

    db.collection("settings").document("payments").update({field: val})
    await update.message.reply_text(f"✅ `{field}` আপডেট হয়েছে!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ব্রডকাস্ট সিস্টেম ---
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("📢 সকল ইউজারের কাছে পাঠানোর জন্য মেসেজটি লিখুন:")
    return BROADCAST_MSG

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    users = db.collection("users").get()
    success, failed = 0, 0
    await update.message.reply_text("🚀 ব্রডকাস্ট শুরু হয়েছে...")
    for u in users:
        try:
            await context.bot.send_message(chat_id=int(u.id), text=msg)
            success += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 ব্রডকাস্ট সম্পন্ন!\n✅ সফল: {success}\n❌ ব্যর্থ: {failed}", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ভাউচার ম্যানেজমেন্ট ---
async def voucher_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("নতুন ভাউচার কোড দিন (যেমন: PROMO50):")
    return ADD_VOUCHER_CODE

async def get_v_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_v_code"] = update.message.text.strip()
    await update.message.reply_text("এই কোড রিডিম করলে কত টাকা ব্যালেন্স পাবে (Amount in BDT)?")
    return ADD_VOUCHER_BAL

async def get_v_bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন:")
        return ADD_VOUCHER_BAL

    code = context.user_data.get("new_v_code")
    db.collection("vouchers").document(code).set({
        "amount": amt,
        "used": False,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    await update.message.reply_text(f"✅ ভাউচার `{code}` তৈরি হয়েছে ({amt} BDT)!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- অ্যাডমিন ম্যানেজমেন্ট ---
async def admin_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != SUPER_ADMIN_ID:
        return
    kb = [
        [InlineKeyboardButton("👑 Add Admin", callback_data="admin_add")],
        [InlineKeyboardButton("❌ Delete Admin", callback_data="admin_del")]
    ]
    await update.message.reply_text("👑 *Admin Management System*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def handle_admin_manage_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    act = query.data.replace("admin_", "")
    if act == "add":
        await query.edit_message_text("নতুন অ্যাডমিনের Telegram Numeric ID দিন:")
        return ADD_ADMIN_ID
    else:
        admins = db.collection("admins").get()
        kb = [[InlineKeyboardButton(f"❌ {a.id}", callback_data=f"deladm_{a.id}")] for a in admins]
        await query.edit_message_text("কোন অ্যাডমিনকে রিমুভ করবেন?", reply_markup=InlineKeyboardMarkup(kb))

async def save_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aid = update.message.text.strip()
    if not aid.isdigit():
        await update.message.reply_text("❌ সঠিক সংখ্যা আইডি দিন:")
        return ADD_ADMIN_ID
    db.collection("admins").document(aid).set({"role": "admin"})
    await update.message.reply_text(f"✅ ID `{aid}` কে অ্যাডমিন করা হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def del_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    aid = query.data.replace("deladm_", "")
    db.collection("admins").document(aid).delete()
    await query.edit_message_text(f"✅ Admin `{aid}` ডিলিট করা হয়েছে!")

# --- রিসেলার, ফোর্স জয়েন ও লিংক সেটআপ ---
async def reseller_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("🤝 রিসেলার রোল দিতে বা সরাতে ইউজারের টেলিগ্রাম ID দিন:")
    return RESELLER_UID

async def save_reseller_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.text.strip()
    ref = db.collection("users").document(uid)
    doc = ref.get()
    if not doc.exists:
        await update.message.reply_text("❌ ইউজার পাওয়া যায়নি।")
        return ConversationHandler.END

    status = not doc.to_dict().get("is_reseller", False)
    ref.update({"is_reseller": status})
    await update.message.reply_text(f"✅ User `{uid}` এর Reseller স্ট্যাটাস: {'Active' if status else 'Deactivated'}", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("নতুন সাপোর্ট ইউজারনেম বা লিংক পাঠান (যেমন: https://t.me/your_support):")
    return SETUP_SUPPORT

async def save_support_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    db.collection("settings").document("misc").update({"support_link": link})
    await update.message.reply_text("✅ সাপোর্ট লিংক সংরক্ষিত হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("নতুন টিউটোরিয়াল ভিডিও লিংক দিন:")
    return SETUP_TUTORIAL

async def save_tutorial_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    db.collection("settings").document("misc").update({"tutorial_link": link})
    await update.message.reply_text("✅ টিউটোরিয়াল লিংক সংরক্ষিত হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

async def prompt_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    await update.message.reply_text("ফোর্স জয়েন চ্যানেলের ইউজারনেম দিন (যেমন: @yourchannel):")
    return SETUP_FORCE_JOIN

async def save_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ch = update.message.text.strip()
    db.collection("settings").document("misc").update({"force_channel": ch})
    await update.message.reply_text("✅ চ্যানেল ফোর্স জয়েন সেট হয়েছে!", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- ক্যানসেল হ্যান্ডলার ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=get_admin_menu())
    return ConversationHandler.END

# --- মেইন অ্যাপ্লিকেশন এক্সিকিউটর ---
def main():
    load_firebase()
    app = Application.builder().token(BOT_TOKEN).build()

    # ১. ফায়ারবেস JSON আপলোড
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔥 Setup Firebase$"), ask_firebase_json)],
        states={UPLOAD_FIREBASE_JSON: [MessageHandler(filters.Document.ALL, save_firebase_json)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ২. বাল্ক স্টক আপলোড
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_prepare_upload, pattern=r"^upstock_")],
        states={UPLOAD_STOCK: [MessageHandler(filters.Document.ALL, process_stock_file)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ৩. ইউজার ম্যানেজমেন্ট
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

    # ৪. পেমেন্ট সেটিংস
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_payment_edit, pattern=r"^payedit_")],
        states={EDIT_PAYMENT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_payment_value)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ৫. ইউজার ডিপোজিট
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

    # ৬. ভাউচার রিডিম (ইউজার)
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛡️ Get Code$"), get_code_prompt)],
        states={REDEEM_VOUCHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_code)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ৭. ভাউচার তৈরি (অ্যাডমিন)
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏷️ Voucher Management$"), voucher_management)],
        states={
            ADD_VOUCHER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_code)],
            ADD_VOUCHER_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_v_bal)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ৮. প্রোডাক্ট অ্যাড ও প্রাইস চেঞ্জ
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

    # ৯. ব্রডকাস্ট
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Broadcast$"), start_broadcast)],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ১০. অ্যাডমিন অ্যাড
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_add$")],
        states={ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_admin)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    ))

    # ১১. রিসেলার, সাপোর্ট, টিউটোরিয়াল ও ফোর্স জয়েন
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

    # --- রেগুলার মেনু ও বাটন ইভেন্ট লিসেনার ---
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

    # ইনলাইন বাটন হ্যান্ডলার
    app.add_handler(CallbackQueryHandler(handle_buy_cat, pattern=r"^buycat_"))
    app.add_handler(CallbackQueryHandler(handle_order, pattern=r"^order_"))
    app.add_handler(CallbackQueryHandler(handle_stock_cat, pattern=r"^stockcat_"))
    app.add_handler(CallbackQueryHandler(user_actions_callback, pattern=r"^uact_ban_"))
    app.add_handler(CallbackQueryHandler(handle_deposit_decide, pattern=r"^dep(app|rej)_"))
    app.add_handler(CallbackQueryHandler(delete_single_product, pattern=r"^delp_"))
    app.add_handler(CallbackQueryHandler(clear_product_stock, pattern=r"^clearstock_"))
    app.add_handler(CallbackQueryHandler(del_admin_cb, pattern=r"^deladm_"))
    app.add_handler(CallbackQueryHandler(handle_admin_manage_cb, pattern=r"^admin_del$"))

    print("New Proxy Market Bot is fully online and running...")
    app.run_polling()

if __name__ == "__main__":
    main()