import io
import logging
from datetime import datetime
import openpyxl

import firebase_admin
from firebase_admin import credentials, firestore, db

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

# ----------------- CONFIGURATION -----------------
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
SUPER_ADMIN_ID = 7072296433  # Replace with primary Admin ID[span_4](start_span)[span_4](end_span)
FIREBASE_CREDENTIALS_PATH = "serviceAccountKey.json"
DATABASE_URL = "https://YOUR_PROJECT_ID.firebaseio.com"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Conversation States
UPLOAD_STOCK, FIND_USER, EDIT_SETTING = range(3)

# ----------------- FIREBASE INITIALIZATION -----------------
cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})
fs = firestore.client()

# Seed Settings & Sample Categories if not exist
def setup_defaults():
    settings_ref = fs.collection("system").document("settings")
    if not settings_ref.get().exists:
        settings_ref.set({
            "dollar_rate": 120.0,
            "bkash": "01XXXXXXXXX",
            "nagad": "01XXXXXXXXX",
            "rocket": "01XXXXXXXXX",
            "binance": "pay_id_here",
            "support_user": "@YourSupportHandle"
        })

    # Default admin setup
    admin_ref = fs.collection("admins").document(str(SUPER_ADMIN_ID))
    if not admin_ref.get().exists:
        admin_ref.set({"added_at": firestore.SERVER_TIMESTAMP, "role": "super_admin"})

setup_defaults()

# ----------------- ACCESS HELPERS -----------------
def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    doc = fs.collection("admins").document(str(user_id)).get()
    return doc.exists

# ----------------- KEYBOARD BUILDERS -----------------
def get_user_menu(user_id: int):
    kb = [
        [KeyboardButton("🎟️ Buy Products")],
        [KeyboardButton("🧑‍💼 My Profile"), KeyboardButton("💵 Deposit")],
        [KeyboardButton("🛡️ Get Code"), KeyboardButton("💬 Support")],
        [KeyboardButton("👑 Tutorial")],
    ]
    if is_admin(user_id):
        kb.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_admin_menu():
    # Exactly matching the admin panel dashboard layout[span_5](start_span)[span_5](end_span)[span_6](start_span)[span_6](end_span)
    kb = [
        [KeyboardButton("💼 Product Management"), KeyboardButton("🔥 Add Stock")],
        [KeyboardButton("🌐 Live Stock"), KeyboardButton("👥 User Management")],
        [KeyboardButton("🔔 Deposit Requests"), KeyboardButton("⚙️ Deposit History")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("🏷️ Voucher Management")],
        [KeyboardButton("👑 Force Join Setup"), KeyboardButton("🧰 Support Setup")],
        [KeyboardButton("🔑 Admin Management"), KeyboardButton("💳 Payment Settings")],
        [KeyboardButton("🤝 Reseller Management"), KeyboardButton("📽️ Tutorial Setup")],
        [KeyboardButton("✅ User Menu")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ----------------- START COMMAND -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u_ref = fs.collection("users").document(str(user.id))
    
    # Register/Update user metadata
    if not u_ref.get().exists:
        u_ref.set({
            "name": user.full_name or "Anonymous",
            "username": user.username or "",
            "balance": 0.0,
            "orders": 0,
            "status": "Active",
            "joined_at": firestore.SERVER_TIMESTAMP
        })
    else:
        u_ref.update({
            "name": user.full_name or "Anonymous",
            "username": user.username or ""
        })

    await update.message.reply_text(
        "✅ মূল মেনু:",
        reply_markup=get_user_menu(user.id)
    )

# ----------------- USER PROFILE -----------------
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    u_doc = fs.collection("users").document(str(user_id)).get()
    settings = fs.collection("system").document("settings").get().to_dict() or {}
    rate = settings.get("dollar_rate", 120.0)

    if u_doc.exists:
        u = u_doc.to_dict()
        bdt = u.get("balance", 0.0)
        usd = bdt / rate if rate > 0 else 0.0
        
        profile_text = (
            f"👥 *USER PROFILE*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Name:* {u.get('name')}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"🌐 *Username:* @{u.get('username', 'N/A')}\n"
            f"💳 *Balance:* {bdt:.1f} BDT ({usd:.2f} USD)\n"
            f"📦 *Orders:* {u.get('orders', 0)}\n"
            f"👑 *Status:* ✅ {u.get('status', 'Active')}"
        ) # Matches visual profile design[span_7](start_span)[span_7](end_span)
        await update.message.reply_text(profile_text, parse_mode="Markdown")

# ----------------- USER: BUY PRODUCTS -----------------
async def buy_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Category selection inline keyboard[span_8](start_span)[span_8](end_span)
    keyboard = [
        [
            InlineKeyboardButton("📧 Hotmail", callback_data="buycat_Hotmail"),
            InlineKeyboardButton("📧 Outlook", callback_data="buycat_Outlook")
        ],
        [
            InlineKeyboardButton("📧 FR_Outlook", callback_data="buycat_FR_Outlook"),
            InlineKeyboardButton("🔒 VPN", callback_data="buycat_VPN")
        ],
        [
            InlineKeyboardButton("🌐 Proxy~IP", callback_data="buycat_Proxy~IP")
        ]
    ]
    await update.message.reply_text(
        "🗂️ প্যাকেজ সিলেক্ট করুন",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def user_category_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("buycat_", "")

    # Query active products under category
    docs = fs.collection("products").where("category", "==", category).stream()
    buttons = []
    
    for doc in docs:
        p = doc.to_dict()
        pid = doc.id
        # Count available stock items
        stock_count = len(list(fs.collection("products").document(pid).collection("items").stream()))
        btn_text = f"🌐 {p.get('name')} | {p.get('price', 0):.1f}৳ | Stock: {stock_count}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"buyitem_{pid}")])

    if not buttons:
        await query.edit_message_text(f"❌ {category} ক্যাটাগরিতে বর্তমানে কোনো প্রোডাক্ট নেই।")
        return

    await query.edit_message_text(
        f"Available {category}:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def user_buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    pid = query.data.replace("buyitem_", "")

    p_ref = fs.collection("products").document(pid)
    p_doc = p_ref.get()
    if not p_doc.exists:
        await query.answer("❌ প্রোডাক্ট পাওয়া যায়নি!", show_alert=True)
        return

    p_data = p_doc.to_dict()
    price = float(p_data.get("price", 0))

    # Fetch 1 stock item from subcollection
    stock_items = list(p_ref.collection("items").limit(1).stream())
    if not stock_items:
        await query.answer("❌ Out of stock!", show_alert=True)
        return

    # Check user balance
    u_ref = fs.collection("users").document(str(user_id))
    u_doc = u_ref.get()
    balance = u_doc.to_dict().get("balance", 0.0) if u_doc.exists else 0.0

    if balance < price:
        await query.answer("❌ পর্যাপ্ত ব্যালেন্স নেই! দয়া করে ডিপোজিট করুন।", show_alert=True)
        return

    item_to_deliver = stock_items[0]
    secret_data = item_to_deliver.to_dict().get("data", "")

    # Execute atomic transaction updates
    u_ref.update({
        "balance": firestore.Increment(-price),
        "orders": firestore.Increment(1)
    })
    # Remove from inventory
    p_ref.collection("items").document(item_to_deliver.id).delete()

    await query.edit_message_text(
        f"✅ *ক্রয় সফল হয়েছে!*\n\n"
        f"📦 পণ্য: *{p_data.get('name')}*\n"
        f"💰 মূল্য: *{price:.1f} BDT*\n\n"
        f"🔑 *ডেলিভারি ডাটা:*\n`{secret_data}`",
        parse_mode="Markdown"
    )

# ----------------- ADMIN DASHBOARD -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("👑 Welcome Admin", reply_markup=get_admin_menu())[span_9](start_span)[span_9](end_span)

async def live_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list(fs.collection("products").stream())
    if not products:
        await update.message.reply_text("🌐 *Live Stock*\n\nকোনো পণ্য যুক্ত করা হয়নি।", parse_mode="Markdown")
        return

    msg = "🌐 *Live Stock*\n\n" # Matches Live Stock report view[span_10](start_span)[span_10](end_span)
    for p in products:
        d = p.to_dict()
        count = len(list(fs.collection("products").document(p.id).collection("items").stream()))
        msg += (
            f"📦 *{d.get('name')}* | Price: {d.get('price', 0):.1f}৳\n"
            f"(Reseller: {d.get('reseller_price', 0):.1f}৳) | Stock: {count}\n\n"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ----------------- ADMIN: PRODUCT MANAGEMENT & DELETION -----------------
async def product_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    kb = [
        [
            InlineKeyboardButton("👑 Add Normal Product", callback_data="adm_add_normal"),
            InlineKeyboardButton("🗂️ Add API Product", callback_data="adm_add_api")
        ],
        [InlineKeyboardButton("💰 Change Price", callback_data="adm_change_price")],
        [InlineKeyboardButton("❌ Delete Product", callback_data="adm_del_product")],
        [InlineKeyboardButton("🧨 Delete Product Stock", callback_data="adm_del_stock")]
    ]
    await update.message.reply_text(
        "⚙️ *Product Management:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def admin_delete_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # As shown in the deletion prompt[span_11](start_span)[span_11](end_span)
    keyboard = [
        [
            InlineKeyboardButton("📧 Hotmail", callback_data="delcat_Hotmail"),
            InlineKeyboardButton("📧 Outlook", callback_data="delcat_Outlook")
        ],
        [
            InlineKeyboardButton("📧 FR_Outlook", callback_data="delcat_FR_Outlook"),
            InlineKeyboardButton("🔒 VPN", callback_data="delcat_VPN")
        ],
        [
            InlineKeyboardButton("🌐 Proxy~IP", callback_data="delcat_Proxy~IP")
        ]
    ]
    await query.edit_message_text(
        "❌ কোন ক্যাটাগরি থেকে প্রোডাক্ট ডিলিট করবেন?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )[span_12](start_span)[span_12](end_span)

async def admin_delete_product_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("delcat_", "")

    products = list(fs.collection("products").where("category", "==", category).stream())
    if not products:
        await query.edit_message_text(f"❌ {category} ক্যাটাগরিতে কোনো পণ্য নেই।")
        return

    buttons = []
    for doc in products:
        d = doc.to_dict()
        buttons.append([InlineKeyboardButton(f"❌ {d.get('name')}", callback_data=f"confirmdel_{doc.id}")]) #[span_13](start_span)[span_13](end_span)

    await query.edit_message_text(
        "❌ কোন প্রোডাক্টটি ডিলিট করবেন?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )[span_14](start_span)[span_14](end_span)

async def admin_confirm_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = query.data.replace("confirmdel_", "")
    
    # Delete subcollection items
    items = fs.collection("products").document(pid).collection("items").stream()
    for it in items:
        it.reference.delete()
        
    fs.collection("products").document(pid).delete()
    await query.answer("প্রোডাক্ট ডিলিট করা হয়েছে!", show_alert=True)
    await query.edit_message_text("✅ প্রোডাক্ট এবং এর সকল স্টক সম্পূর্ণ ডিলিট করা হয়েছে।")

# ----------------- ADMIN: STOCK UPLOAD (CONVERSATION) -----------------
async def start_add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton("📧 Hotmail", callback_data="stkcat_Hotmail"),
            InlineKeyboardButton("📧 Outlook", callback_data="stkcat_Outlook")
        ],
        [
            InlineKeyboardButton("📧 FR_Outlook", callback_data="stkcat_FR_Outlook"),
            InlineKeyboardButton("🌐 Proxy~IP", callback_data="stkcat_Proxy~IP")
        ]
    ]
    await update.message.reply_text(
        "🗂️ কোন ক্যাটাগরিতে স্টক অ্যাড করবেন?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stock_select_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.replace("stkcat_", "")

    products = list(fs.collection("products").where("category", "==", cat).stream())
    if not products:
        await query.edit_message_text(f"❌ {cat} ক্যাটাগরিতে কোনো প্রোডাক্ট পাওয়া যায়নি।")
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(p.to_dict().get("name"), callback_data=f"stkprod_{p.id}")] for p in products]
    await query.edit_message_text("পণ্য সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(buttons))

async def stock_select_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = query.data.replace("stkprod_", "")
    context.user_data["target_pid"] = pid

    p_doc = fs.collection("products").document(pid).get()
    pname = p_doc.to_dict().get("name", "Product") if p_doc.exists else "Product"

    instruction = (
        f"🗂️ *{pname}* এর জন্য Excel (.xlsx) অথবা Text (.txt) ফাইলটি পাঠান:\n\n"
        f"📌 *আপলোডের সঠিক ফরম্যাট:*\n"
        f"✏️ *TXT ফাইল হলে:*\n"
        f"`Host:Port:Username:Password` (মাঝে : থাকবে)\n\n"
        f"🧪 *Excel ফাইল হলে:*\n"
        f"• কলাম A = Host\n"
        f"• কলাম B = Port\n"
        f"• কলাম C = Username\n"
        f"• কলাম D = Password"
    ) # Format instruction[span_15](start_span)[span_15](end_span)
    await query.edit_message_text(instruction, parse_mode="Markdown")
    return UPLOAD_STOCK

async def parse_and_upload_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    pid = context.user_data.get("target_pid")

    if not pid:
        await update.message.reply_text("❌ সেশন মেয়াদোত্তীর্ণ হয়েছে। পুনরায় চেষ্টা করুন।")
        return ConversationHandler.END

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()
    entries = []

    # Parse plain TXT
    if doc.file_name.endswith(".txt"):
        lines = file_bytes.decode("utf-8", errors="ignore").splitlines()
        for line in lines:
            clean = line.strip()
            if clean:
                entries.append(clean)

    # Parse Excel (.xlsx)
    elif doc.file_name.endswith(".xlsx"):
        wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)
        sheet = wb.active
        for row in sheet.iter_rows(values_only=True):
            if any(row):
                # Columns A, B, C, D joined by ':'
                row_vals = [str(col).strip() for col in row[:4] if col is not None]
                if len(row_vals) == 4:
                    entries.append(":".join(row_vals))

    if not entries:
        await update.message.reply_text("❌ ফাইলে কোনো ডাটা পাওয়া যায়নি অথবা কলাম বিন্যাস ভুল।")
        return ConversationHandler.END

    # Push to Firebase Firestore in batches
    batch = fs.batch()
    items_ref = fs.collection("products").document(pid).collection("items")
    count = 0

    for item_data in entries:
        new_doc = items_ref.document()
        batch.set(new_doc, {"data": item_data, "added_at": firestore.SERVER_TIMESTAMP})
        count += 1
        if count % 400 == 0:  # Firestore batch limit is 500
            batch.commit()
            batch = fs.batch()
    batch.commit()

    await update.message.reply_text(
        f"✅ মোট {len(entries)} টি স্টক সফলভাবে Firebase এ সেভ হয়েছে!",
        reply_markup=get_admin_menu()
    )
    return ConversationHandler.END

# ----------------- ADMIN: PAYMENT SETTINGS -----------------
async def payment_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    settings = fs.collection("system").document("settings").get().to_dict() or {}
    rate = settings.get("dollar_rate", 120.0)

    # Matches payment gateway buttons[span_16](start_span)[span_16](end_span)
    kb = [
        [InlineKeyboardButton("🪶 Edit Bkash Number", callback_data="payedit_bkash")],
        [InlineKeyboardButton("🪶 Edit Nagad Number", callback_data="payedit_nagad")],
        [InlineKeyboardButton("🪶 Edit Rocket Number", callback_data="payedit_rocket")],
        [InlineKeyboardButton("🪶 Edit Binance Number", callback_data="payedit_binance")],
        [InlineKeyboardButton(f"🪙 Edit Dollar Rate (Current: {rate:.1f} BDT)", callback_data="payedit_dollar_rate")],
    ]
    await update.message.reply_text(
        "⚙️ *কোন পেমেন্ট মেথডের নাম্বার পরিবর্তন করবেন?*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )[span_17](start_span)[span_17](end_span)

async def select_payment_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("payedit_", "")
    context.user_data["edit_field"] = key

    await query.edit_message_text(f"নতুন মান লিখুন `{key}` এর জন্য:", parse_mode="Markdown")
    return EDIT_SETTING

async def save_payment_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    key = context.user_data.get("edit_field")

    if key == "dollar_rate":
        try:
            val = float(val)
        except ValueError:
            await update.message.reply_text("❌ অনুগ্রহ করে সঠিক সংখ্যা লিখুন।")
            return EDIT_SETTING

    fs.collection("system").document("settings").update({key: val})
    await update.message.reply_text(f"✅ `{key}` সফলভাবে আপডেট করা হয়েছে!", parse_mode="Markdown", reply_markup=get_admin_menu())
    return ConversationHandler.END

# ----------------- ADMIN: USER MANAGEMENT -----------------
async def user_management_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text("👥 ইউজারের টেলিগ্রাম ID বা Username দিন:")[span_18](start_span)[span_18](end_span)
    return FIND_USER

async def handle_user_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_query = update.message.text.strip().replace("@", "")
    target_doc = None

    if search_query.isdigit():
        target_doc = fs.collection("users").document(search_query).get()
    
    if not target_doc or not target_doc.exists:
        # Search by username attribute
        matches = list(fs.collection("users").where("username", "==", search_query).limit(1).stream())
        if matches:
            target_doc = matches[0]

    if not target_doc or not target_doc.exists:
        await update.message.reply_text("❌ ইউজার খুঁজে পাওয়া যায়নি।")
        return ConversationHandler.END

    u = target_doc.to_dict()
    uid = target_doc.id
    settings = fs.collection("system").document("settings").get().to_dict() or {}
    rate = settings.get("dollar_rate", 120.0)
    bdt = u.get("balance", 0.0)
    usd = bdt / rate if rate > 0 else 0.0

    profile_card = (
        f"👥 *USER PROFILE*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Name:* {u.get('name')}\n"
        f"🆔 *ID:* `{uid}`\n"
        f"🌐 *Username:* @{u.get('username', 'N/A')}\n"
        f"💳 *Balance:* {bdt:.1f} BDT ({usd:.2f} USD)\n"
        f"📦 *Orders:* {u.get('orders', 0)}\n"
        f"👑 *Status:* ✅ {u.get('status', 'Active')}"
    ) #[span_19](start_span)[span_19](end_span)

    kb = [
        [InlineKeyboardButton("🚫 Ban", callback_data=f"uban_{uid}")],
        [
            InlineKeyboardButton("💰 Add Balance", callback_data=f"uadd_{uid}"),
            InlineKeyboardButton("✂️ Cut Balance", callback_data=f"ucut_{uid}")
        ],
        [InlineKeyboardButton("💬 Send Message", callback_data=f"umsg_{uid}")]
    ] #[span_20](start_span)[span_20](end_span)

    await update.message.reply_text(profile_card, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ----------------- ADMIN: DEPOSIT REQUESTS -----------------
async def deposit_requests_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    reqs = list(fs.collection("deposits").where("status", "==", "pending").stream())
    if not reqs:
        await update.message.reply_text("❌ কোনো পেন্ডিং ডিপোজিট নেই।")[span_21](start_span)[span_21](end_span)
        return

    for doc in reqs:
        d = doc.to_dict()
        msg = f"🔔 *Deposit Request:*\nUser: `{d.get('user_id')}`\nAmount: {d.get('amount')} BDT\nTxID: `{d.get('trxid')}`"
        kb = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"apprdep_{doc.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"rejdep_{doc.id}")
            ]
        ]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ----------------- CANCEL CONVERSATION -----------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("অপারেশন বাতিল করা হয়েছে।", reply_markup=get_user_menu(update.effective_user.id))
    return ConversationHandler.END

# ----------------- MAIN APP LAUNCHER -----------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Stock upload conversation
    stock_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(stock_select_product, pattern=r"^stkprod_")
        ],
        states={
            UPLOAD_STOCK: [MessageHandler(filters.Document.ALL, parse_and_upload_stock)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Payment setting modification conversation
    payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_payment_key, pattern=r"^payedit_")],
        states={
            EDIT_SETTING: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_payment_setting)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # User management conversation
    user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👥 User Management$"), user_management_entry)],
        states={
            FIND_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_lookup)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Base Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🎟️ Buy Products$"), buy_products_menu))
    app.add_handler(MessageHandler(filters.Regex("^🧑‍💼 My Profile$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^👑 Admin Panel$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^🌐 Live Stock$"), live_stock))
    app.add_handler(MessageHandler(filters.Regex("^🔥 Add Stock$"), start_add_stock))
    app.add_handler(MessageHandler(filters.Regex("^💼 Product Management$"), product_management_menu))
    app.add_handler(MessageHandler(filters.Regex("^💳 Payment Settings$"), payment_settings_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔔 Deposit Requests$"), deposit_requests_view))
    app.add_handler(MessageHandler(filters.Regex("^✅ User Menu$"), start))

    # Dynamic Callback Handlers
    app.add_handler(CallbackQueryHandler(user_category_click, pattern=r"^buycat_"))
    app.add_handler(CallbackQueryHandler(user_buy_product, pattern=r"^buyitem_"))
    app.add_handler(CallbackQueryHandler(stock_select_category, pattern=r"^stkcat_"))
    app.add_handler(CallbackQueryHandler(admin_delete_product_category, pattern=r"^adm_del_product$"))
    app.add_handler(CallbackQueryHandler(admin_delete_product_list, pattern=r"^delcat_"))
    app.add_handler(CallbackQueryHandler(admin_confirm_delete_product, pattern=r"^confirmdel_"))

    # Register conversations
    app.add_handler(stock_conv)
    app.add_handler(payment_conv)
    app.add_handler(user_conv)

    print("Firebase Bot Started successfully.")
    app.run_polling()

if __name__ == "__main__":
    main()