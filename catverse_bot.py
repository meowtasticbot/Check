import os
import random
import time
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from telegram.constants import ParseMode
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = 7789325573

client = MongoClient(MONGO_URI)
db = client["catverse"]
cats = db["cats"]
global_state = db["global"]
leaderboard_history = db["leaderboard_history"]

# ================= LEVELS =================

LEVELS = [
    ("🐱 Kitten", 0),
    ("😺 Teen Cat", 1000),
    ("😼 Rogue Cat", 5000),
    ("🐯 Alpha Cat", 20000),
    ("👑 Legend Cat", 1600000),
]

# ================= Helper Functions =================

def is_owner_user(user_id: int) -> bool:
    return user_id == OWNER_ID
    
# ================= DATABASE =================

def get_cat(user):
    cat = cats.find_one({"_id": user.id})
    default_data = {
        "name": user.first_name,
        "coins": 500,
        "fish": 2,
        "xp": 0,
        "kills": 0,
        "deaths": 0,
        "premium": True,
        "inventory": {**{item: 0 for item in SHOP_ITEMS}, **{gift: 0 for gift in GIFT_ITEMS}},
        "dna": {"aggression": 1, "intelligence": 1, "luck": 1, "charm": 1},
        "level": "🐱 Kitten",
        "last_msg": 0,
        "protected_until": None,
        "last_daily": None,
        "last_claim": None,  # 👈 ADD THI
        "last_rob": {},
        "inventory": {"fish_bait": 0},
        "fish_streak": 0,
        "last_fish_date": None,
        "fish_total_earned": 0,
        "wanted": 0,
        "created": datetime.now(timezone.utc),
    }
    if not cat:
        cat = {"_id": user.id, **default_data}
        cats.insert_one(cat)
    else:
        update_fields = {k: v for k, v in default_data.items() if k not in cat}
        if update_fields:
            cats.update_one({"_id": user.id}, {"$set": update_fields})
            cat.update(update_fields)
    return cat

def evolve(cat):
    current_xp = cat.get("xp", 0)
    old_level = cat.get("level", "🐱 Kitten")

    new_level = old_level
    for name, xp_required in reversed(LEVELS):
        if current_xp >= xp_required:
            new_level = name
            break

    cat["level"] = new_level
    return old_level != new_level  # Returns True if leveled up

def is_protected(cat):
    protected_until = cat.get("protected_until")
    if not protected_until:
        return False

    # 🛠 Convert naive datetime → UTC aware
    if protected_until.tzinfo is None:
        protected_until = protected_until.replace(tzinfo=timezone.utc)

    return protected_until > datetime.now(timezone.utc)
    
def calculate_global_rank(user_id):
    all_cats = list(cats.find().sort("coins", -1))
    for idx, c in enumerate(all_cats, 1):
        if c["_id"] == user_id:
            return idx
    return 0
    
# 👑 OWNER GOD MODE
    if is_owner_user(user.id):
        cat["coins"] = float("inf")
        cat["xp"] = float("inf")
        cat["level"] = "👑 Legend Cat"
        cat["dna"] = {
            "aggression": 100,
            "intelligence": 100,
            "luck": 100,
            "charm": 100,
        }
    return cat
    
# ================= GAME GUIDE =================

async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    level_text = "\n".join([f"{lvl} → {req} XP" for lvl, req in LEVELS])
    text = (
        "🐱 *CATVERSE GUIDE*\n\n"

        "💰 Economy:\n"
        "  /daily — Daily coins (DM only)\n"
        "  /claim — Group reward (1000+ members)\n"
        "  /bal — Check balance\n"
        "  /give <amount> — Gift coins (reply)\n\n"

        "⚔️ Combat:\n"
        "  /rob <amount> — Rob a cat\n"
        "  /kill — Attack a cat\n"
        "  /protect — 24h protection\n\n"

        "🛒 Shop & Items:\n"
        "  /shop — Shop items\n"
        "     🐟 Fish Bait, 🚔 Bail Pass, 🍀 Luck Boost, 🛡 Shield, 💣 Shield Breaker\n"
        "  /inventory — Your items\n"
        "  /use <item> — Activate item (shield, shield_breaker, luck_boost, bail_pass, fish_bait)\n\n"

        "🐟 Fishing & Events:\n"
        "  Chat to gain XP & trigger fish events\n"
        "  /fish — Catch fish, rare boosted by Fish Bait\n\n"

        "📊 Profile & Stats:\n"
        "  /me — Profile\n"
        "  /toprich — Richest cats\n"
        "  /topkill — Top fighters\n"
        "  /xp — Check XP & DNA stats\n"
        "  Levels: 🐱 Kitten → 😺 Teen → 😼 Rogue → 🐯 Alpha → 👑 Legend\n"
        f"📈 Levels:\n{level_text}"
    )
    await update.message.reply_text(text)

# ---- Passive XP + Activity XP System ----
async def on_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    cat = get_cat(update.effective_user)
    now = time.time()

    # Anti-spam cooldown (4 sec)
    if now - cat.get("last_msg", 0) < 4:
        return

    cat["last_msg"] = now

    # Base chat XP
    xp_gain = random.randint(2, 5)

    # Longer messages = little more XP
    msg_len = len(update.message.text)
    if msg_len > 80:
        xp_gain += 2
    elif msg_len > 40:
        xp_gain += 1

    cat["xp"] += xp_gain

    # Random DNA stat improvement (UNCHANGED)
    stat = random.choice(list(cat["dna"]))
    cat["dna"][stat] += random.randint(1, 2)

    # 🔼 LEVEL CHECK (XP BASED NOW)
    leveled_up = evolve(cat)

    if leveled_up:
        level_msg = (
            f"🎉 {update.effective_user.first_name}'s cat leveled up!\n"
            f"🏆 New Rank: {cat['level']}"
        )

        # Group notification
        await update.message.reply_text(level_msg)

        # DM notification
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=f"📩 LEVEL UP!\nYour cat is now {cat['level']} 🎉"
            )
        except:
            pass

    # 🎁 Small random bonus event (2%)
    if random.random() < 0.02:
        bonus = random.randint(10, 25)
        cat["coins"] += bonus
        await update.message.reply_text(f"💰 You found {bonus} bonus coins while chatting!")

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    
async def fish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cat = get_cat(user)
    inventory = cat.get("inventory", {})
    now = datetime.now(timezone.utc)

    today = now.date().isoformat()
    last_date = cat.get("last_fish_date")
    streak = cat.get("fish_streak", 0)

    if last_date == today:
        streak += 1
    else:
        streak = 1

    streak_bonus = min(streak * 20, 200)

    bait_bonus = 0
    bait_msg = ""
    if inventory.get("fish_bait", 0) > 0:
        bait_bonus = random.randint(50, 150)
        inventory["fish_bait"] -= 1
        bait_msg = "🐟 Magic bait boosted your luck!\n"

    roll = random.randint(1, 100)

    jackpot_msgs = [
        "💎 LEGENDARY DRAGON FISH!",
        "🐉 Mythical sea beast with treasure!",
        "🌟 Ancient glowing fish surfaced!",
    ]

    profit_msgs = [
        "🎣 Smooth catch!",
        "🐠 Coin-filled fish!",
        "🌊 Lucky wave reward!",
        "🏝️ Pirate fish haul!",
    ]

    loss_msgs = [
        "🦈 Sharks robbed you!",
        "🌪️ Storm destroyed net!",
        "🐙 Octopus tax taken!",
        "🏴‍☠️ Pirates stole catch!",
    ]

    coins_change = 0
    msg = ""

    # 🎉 JACKPOT
    if roll == 1:
        base = random.randint(5000, 10000)
        total = base + bait_bonus + streak_bonus
        coins_change = total
        msg = (
            f"{bait_msg}{random.choice(jackpot_msgs)}\n"
            f"💰 Base Catch: {base}\n"
            f"🎁 Streak Bonus: {streak_bonus}\n"
            f"✨ Bait Bonus: {bait_bonus}\n"
            f"🔥 JACKPOT TOTAL: +🪙 {total}"
        )

    # 🟢 NORMAL PROFIT
    elif 2 <= roll <= 71:
        base = random.randint(400, 1000)
        total = base + bait_bonus + streak_bonus
        coins_change = total
        msg = (
            f"{bait_msg}{random.choice(profit_msgs)}\n"
            f"💰 Base Catch: {base}\n"
            f"🎁 Streak Bonus: {streak_bonus}\n"
            f"✨ Bait Bonus: {bait_bonus}\n"
            f"🪙 TOTAL GAIN: +{total}"
        )

    # 🔴 LOSS
    else:
        loss = random.randint(1000, 2000)
        current = cat.get("coins", 0)

        if current < loss:
            loss = max(50, int(current * 0.5))

        coins_change = -loss
        msg = f"{random.choice(loss_msgs)}\n💸 Lost 🪙 {loss}"

    new_balance = max(0, cat.get("coins", 0) + coins_change)

    update_data = {
        "coins": new_balance,
        "fish_streak": streak,
        "last_fish_date": today,
        "inventory": inventory,
    }

    if coins_change > 0:
        update_data["fish_total_earned"] = cat.get("fish_total_earned", 0) + coins_change

    cats.update_one({"_id": user.id}, {"$set": update_data})

    await update.message.reply_text(msg)

# ---------------- LEADERBOARD ----------------
async def fishlb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = cats.find().sort("fish_total_earned", -1).limit(5)

    text = "🏆 Top Fishing Legends 🏆\n\n"
    for i, u in enumerate(top_users, start=1):
        text += f"{i}. {u.get('name','Cat')} — 🪙 {u.get('fish_total_earned',0)}\n"

    await update.message.reply_text(text)
    
# ---- /xp command ----
async def xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)

    # 👑 OWNER GOD MODE XP
    if is_owner_user(update.effective_user.id):
        text = (
            f"👑 *OWNER GOD STATS*\n\n"
            f"Level: 👑 Legend Cat\n"
            f"XP: ∞\n\n"
            f"🧬 DNA Stats:\n"
            f"▫️ Aggression: 100\n"
            f"▫️ Intelligence: 100\n"
            f"▫️ Luck: 100\n"
            f"▫️ Charm: 100\n"
            f"🐟 Fish: ∞"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        return

    # 👤 NORMAL USER
    stats = cat["dna"]
    text = (
        f"📊 *Your Cat Stats*\n"
        f"Level: {cat['level']}\n"
        f"XP: {cat['xp']}\n\n"
        f"🧬 DNA Stats:\n"
        f"▫️ Aggression: {stats['aggression']}\n"
        f"▫️ Intelligence: {stats['intelligence']}\n"
        f"▫️ Luck: {stats['luck']}\n"
        f"▫️ Charm: {stats['charm']}\n"
        f"🐟 Fish: {cat['fish']}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ================= ECONOMY =================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ✅ Only in DM
    if update.effective_chat.type != "private":
        return await update.message.reply_text("⚠️ Daily reward DM only.")

    cat = get_cat(update.effective_user)
    now = datetime.utcnow()  # ✅ FIXED

    last = cat.get("last_daily")
    if last and (now - last) < timedelta(hours=24):
        return await update.message.reply_text("⏳ Already claimed today!")

    cat["coins"] += 400
    cat["last_daily"] = now
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})

    await update.message.reply_text("🎁 You got $400!")


# 🆕 GROUP CLAIM REWARD (1000+ MEMBERS ONLY)
async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    # ❌ Not allowed in private chat
    if chat.type == "private":
        return await update.message.reply_text("❌ Use /daily in DM for personal reward.")

    # 👥 Check group size
    try:
        members = await context.bot.get_chat_member_count(chat.id)
    except:
        return await update.message.reply_text("⚠️ Unable to verify group size.")

    if members < 1000:
        return await update.message.reply_text("🚫 This command works only in groups with 1000+ members.")

    cat = get_cat(update.effective_user)
    now = datetime.utcnow()  # ✅ FIXED

    last = cat.get("last_claim")
    if last and (now - last) < timedelta(hours=24):
        return await update.message.reply_text("⏳ You already claimed a group reward today!")

    reward = 250  # Group reward amount

    cat["coins"] += reward
    cat["last_claim"] = now
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})

    await update.message.reply_text(f"🏆 Group reward claimed! You received ${reward}")


# 💰 CHECK BALANCE
async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    await update.message.reply_text(f"💰 Balance: ${cat['coins']}")


# 💸 GIVE MONEY (with OWNER protection)
async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ❌ OWNER PROTECTION: Agar reply kiya gaya user OWNER hai
    if update.message.reply_to_message and is_owner_user(update.message.reply_to_message.from_user.id):
        await update.message.reply_text(
            "👑 Hold on! This cat is the OWNER of the bot 😼\n"
            "💰 You can't give or take money from them.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text("❗ Reply with /give <amount>")

    sender = get_cat(update.effective_user)
    receiver = get_cat(update.message.reply_to_message.from_user)

    try:
        amount = int(context.args[0])
        if amount <= 0:
            return await update.message.reply_text("Enter a valid amount.")
    except:
        return await update.message.reply_text("Enter a valid number.")

    if sender["coins"] < amount:
        return await update.message.reply_text("Not enough money.")

    tax = int(amount * 0.05)
    final = amount - tax

    sender["coins"] -= amount
    receiver["coins"] += final

    cats.update_one({"_id": sender["_id"]}, {"$set": sender})
    cats.update_one({"_id": receiver["_id"]}, {"$set": receiver})

    await update.message.reply_text(f"🐾 Sent ${final} after tax!")
    
# ================== SHOP DATA ==================
GIFT_ITEMS = {
    "rose": {"price": 500, "emoji": "🌹"},
    "chocolate": {"price": 800, "emoji": "🍫"},
    "ring": {"price": 2000, "emoji": "💍"},
    "teddy": {"price": 1500, "emoji": "🧸"},
    "pizza": {"price": 600, "emoji": "🍕"},
    "surprise_box": {"price": 2500, "emoji": "🎁"},
    "puppy": {"price": 3000, "emoji": "🐶"},
    "cake": {"price": 1000, "emoji": "🎂"},
    "love_letter": {"price": 400, "emoji": "💌"},
    "cat": {"price": 2500, "emoji": "🐱"},
}

SHOP_ITEMS = {
    "fish_bait": {"price": 80, "desc": "🐟 Increases chance to find rare magic fish"},
    "bail_pass": {"price": 400, "desc": "🚔 Escape wanted penalty"},
    "luck_boost": {"price": 250, "desc": "🍀 Improves robbery success"},
    "shield": {"price": 350, "desc": "🛡 Blocks robberies for 1 day"},
    "shield_breaker": {"price": 800, "desc": "💣 Breaks target protection"},
}

# ================== OWNER LOCK ==================
def is_owner(query, context):
    return context.chat_data.get("shop_owner") == query.from_user.id

# ================== SHOP COMMAND ==================
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["shop_owner"] = update.effective_user.id

    keyboard = [
        [InlineKeyboardButton("🧪 Items Shop", callback_data="shop:items")],
        [InlineKeyboardButton("🎁 Gift Shop", callback_data="giftshop:open")]
    ]

    await update.message.reply_text(
        "🛒 *Catverse Black Market*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================== SHOP CALLBACK SYSTEM ==================
async def shop_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_owner(query, context):
        return await query.answer("🚫 This shop isn't yours!", show_alert=True)

    cat = get_cat(query.from_user)

    if "inventory" not in cat or not isinstance(cat["inventory"], dict):
        cat["inventory"] = {}

    data = query.data

    # ===== MAIN MENU =====
    if data == "shop:main":
        keyboard = [
            [InlineKeyboardButton("🧪 Items Shop", callback_data="shop:items")],
            [InlineKeyboardButton("🎁 Gift Shop", callback_data="giftshop:open")]
        ]
        await query.edit_message_text("🛒 *Catverse Black Market*", parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    # ===== OPEN ITEMS SHOP =====
    elif data == "shop:items":
        keyboard = [[InlineKeyboardButton(i.replace('_',' ').title(), callback_data=f"shop:view:{i}")] for i in SHOP_ITEMS]
        keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="shop:main")])
        await query.edit_message_text("🧪 *Black Market Items*", parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    # ===== OPEN GIFT SHOP =====
    elif data == "giftshop:open":
        keyboard = [[InlineKeyboardButton(f"{v['emoji']} {k.title()} - ${v['price']}",
                                          callback_data=f"giftshop:view:{k}")] for k, v in GIFT_ITEMS.items()]
        keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="shop:main")])
        await query.edit_message_text("🎁 *Gift Shop*", parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    # ===== VIEW NORMAL ITEM =====
    elif data.startswith("shop:view:"):
        item = data.split(":")[2]
        info = SHOP_ITEMS[item]
        owned = cat["inventory"].get(item, 0)

        text = f"🧾 *{item.replace('_',' ').title()}*\n\n{info['desc']}\n\n💰 Price: *${info['price']}*\n📦 Owned: *{owned}*"
        keyboard = [
            [InlineKeyboardButton("🛒 Purchase", callback_data=f"shop:buy:{item}")],
            [InlineKeyboardButton("⬅ Back", callback_data="shop:items")]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # ===== BUY NORMAL ITEM =====
    elif data.startswith("shop:buy:"):
        item = data.split(":")[2]
        price = SHOP_ITEMS[item]["price"]

        if cat["coins"] < price:
            return await query.answer("💸 You don't have enough coins!", show_alert=True)

        cat["coins"] -= price
        cat["inventory"][item] = cat["inventory"].get(item, 0) + 1
        cats.update_one({"_id": cat["_id"]}, {"$set": {"coins": cat["coins"], "inventory": cat["inventory"]}})

        await query.edit_message_text(
            f"✅ Purchased *{item.replace('_',' ').title()}*\n💰 Balance: ${cat['coins']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="shop:items")]])
        )

    # ===== VIEW GIFT =====
    elif data.startswith("giftshop:view:"):
        item = data.split(":")[2]
        info = GIFT_ITEMS[item]
        owned = cat["inventory"].get(item, 0)

        text = f"{info['emoji']} *{item.title()}*\n\n💰 Price: *${info['price']}*\n📦 Owned: *{owned}*"
        keyboard = [
            [InlineKeyboardButton("🛒 Buy Gift", callback_data=f"giftshop:buy:{item}")],
            [InlineKeyboardButton("⬅ Back", callback_data="giftshop:open")]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # ===== BUY GIFT =====
    elif data.startswith("giftshop:buy:"):
        item = data.split(":")[2]
        price = GIFT_ITEMS[item]["price"]

        if cat["coins"] < price:
            return await query.answer("💸 You don't have enough coins!", show_alert=True)

        cat["coins"] -= price
        cat["inventory"][item] = cat["inventory"].get(item, 0) + 1
        cats.update_one({"_id": cat["_id"]}, {"$set": {"coins": cat["coins"], "inventory": cat["inventory"]}})

        await query.edit_message_text(
            f"🎁 Gift Purchased: {GIFT_ITEMS[item]['emoji']} *{item.title()}*\n💰 Balance: ${cat['coins']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="giftshop:open")]])
        )

# ----------------- /gift COMMAND -----------------
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = get_cat(update.effective_user)

    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to someone to gift 🎁")

    if not context.args:
        return await update.message.reply_text("Usage: /gift <item>")

    item = context.args[0].lower()
    if item not in GIFT_ITEMS:
        return await update.message.reply_text("Invalid gift item.")

    if sender.get("inventory", {}).get(item, 0) <= 0:
        return await update.message.reply_text("You don't own this gift.")

    receiver_user = update.message.reply_to_message.from_user
    receiver = get_cat(receiver_user)

    # Deduct from sender
    sender["inventory"][item] -= 1
    if sender["inventory"][item] <= 0:
        del sender["inventory"][item]

    # Add to receiver
    receiver.setdefault("inventory", {})
    receiver["inventory"][item] = receiver["inventory"].get(item, 0) + 1

    # Update DB
    cats.update_one({"_id": sender["_id"]}, {"$set": {"inventory": sender["inventory"]}})
    cats.update_one({"_id": receiver["_id"]}, {"$set": {"inventory": receiver["inventory"]}})

    # Prepare reply
    if item == "kiss":
        # Clickable user link
        user_link = f"[{receiver_user.first_name}](tg://user?id={receiver_user.id})"
        text = f"{GIFT_ITEMS[item]['emoji']} Gift sent to {user_link} 💖"
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"{GIFT_ITEMS[item]['emoji']} Gift sent to {receiver_user.first_name} 💖")
        
# ================= INVENTORY =================
async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    inv = cat.get("inventory", {})

    msg = "🎒 *Your Inventory*\n\n"

    # ----- Normal Items -----
    normal_items = [f"▫️ {k.replace('_',' ').title()} × {v}" for k, v in inv.items() if k in SHOP_ITEMS and v > 0]
    if normal_items:
        msg += "🛒 *Shop Items:*\n" + "\n".join(normal_items) + "\n\n"
    else:
        msg += "🛒 *Shop Items:* Empty 😿\n\n"

    # ----- Gift Items -----
    gift_items = [f"{GIFT_ITEMS[k]['emoji']} {k.title()} × {v}" for k, v in inv.items() if k in GIFT_ITEMS and v > 0]
    if gift_items:
        msg += "🎁 *Gift Items:*\n" + "\n".join(gift_items)
    else:
        msg += "🎁 *Gift Items:* Empty 😿"

    await update.message.reply_text(msg, parse_mode="Markdown")

# -------------------- ITEM USE LOGIC --------------------

async def use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)  # get user data

    if not context.args:
        return await update.message.reply_text(
            "Usage: /use <item>\nExample: /use shield"
        )

    item = context.args[0].lower()
    inventory = cat.get("inventory", {})

    # ------------------- SHIELD -------------------
    if item == "shield":
        if inventory.get("shield", 0) <= 0:
            return await update.message.reply_text("❌ You don't own a shield.")

        inventory["shield"] -= 1
        cat["shield_until"] = datetime.now(timezone.utc) + timedelta(days=1)
        await update.message.reply_text("🛡 Shield activated for 24 hours!")

    # ------------------- SHIELD BREAKER -------------------
    elif item == "shield_breaker":
        if inventory.get("shield_breaker", 0) <= 0:
            return await update.message.reply_text("❌ You don't own a Shield Breaker.")
        # For shield breaker, it is consumed automatically in rob command
        return await update.message.reply_text("ℹ️ Use a Shield Breaker during a robbery!")

    # ------------------- LUCK BOOST -------------------
    elif item == "luck_boost":
        if inventory.get("luck_boost", 0) <= 0:
            return await update.message.reply_text("❌ You don't own a Luck Boost.")
        # For luck boost, it is consumed automatically in rob command
        return await update.message.reply_text("ℹ️ Luck Boost will be applied automatically on next robbery!")

    # ------------------- BAIL PASS -------------------
    elif item == "bail_pass":
        if inventory.get("bail_pass", 0) <= 0:
            return await update.message.reply_text("❌ You don't own a Bail Pass.")
        # Used automatically when jailed
        return await update.message.reply_text("ℹ️ Bail Pass will be used automatically if jailed!")

    # ------------------- FISH BAIT -------------------
    elif item == "fish_bait":
        if inventory.get("fish_bait", 0) <= 0:
            return await update.message.reply_text("❌ You don't own Fish Bait.")
        # Consumed automatically in fishing
        return await update.message.reply_text("ℹ️ Fish Bait will be consumed automatically in next fishing event!")

    else:
        return await update.message.reply_text("❌ Unknown item!")

    # Update cat inventory & db
    cat["inventory"] = inventory
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})


# ------------------- HELPER FUNCTION -------------------
def has_active_shield(cat):
    """Check if the cat has an active shield protection"""
    return cat.get("shield_until") and cat["shield_until"] > datetime.now(timezone.utc)


# ------------------- ROB COMMAND LOGIC EXAMPLES -------------------
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attacker = get_cat(update.effective_user)
    target_user = update.message.reply_to_message.from_user
    target = get_cat(target_user)

    # 1️⃣ Check Shield
    if has_active_shield(target):
        if attacker["inventory"].get("shield_breaker", 0) > 0:
            attacker["inventory"]["shield_breaker"] -= 1
            target["shield_until"] = None
            await update.message.reply_text("💣 You broke the target's shield!")
        else:
            return await update.message.reply_text("🛡 Target is protected by a shield! Use a Shield Breaker.")

    # 2️⃣ Luck Boost
    luck_bonus = 0
    if attacker["inventory"].get("luck_boost", 0) > 0:
        luck_bonus = 20
        attacker["inventory"]["luck_boost"] -= 1
        await update.message.reply_text("🍀 Luck Boost applied! +20% success chance.")

    # 3️⃣ Determine success
    success_chance = 50 + luck_bonus
    if random.randint(1, 100) <= success_chance:
        reward = 200
        attacker["coins"] += reward
        await update.message.reply_text(f"✅ Robbery successful! You gained ${reward}")
    else:
        # Check Bail Pass
        if attacker["inventory"].get("bail_pass", 0) > 0:
            attacker["inventory"]["bail_pass"] -= 1
            await update.message.reply_text("🚔 Bail Pass used! You escaped jail.")
        else:
            attacker["jail_until"] = datetime.now(timezone.utc) + timedelta(minutes=30)
            await update.message.reply_text("❌ Robbery failed! You are jailed for 30 minutes.")

    # Update attacker & target
    cats.update_one({"_id": attacker["_id"]}, {"$set": attacker})
    cats.update_one({"_id": target["_id"]}, {"$set": target})


# ------------------- FISHING EVENT EXAMPLE -------------------
async def moon_mere_papa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    inventory = cat.get("inventory", {})

    rare_bonus = 0
    if inventory.get("fish_bait", 0) > 0:
        rare_bonus = 15
        inventory["fish_bait"] -= 1
        await update.message.reply_text("🐟 Fish Bait used! +15% rare chance")

    if random.randint(1, 100) <= 10 + rare_bonus:
        reward = 500
        await update.message.reply_text(f"🎉 You caught a rare fish! +${reward}")
    else:
        reward = 100
        await update.message.reply_text(f"🐟 You caught a normal fish. +${reward}")

    cat["coins"] += reward
    cat["inventory"] = inventory
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
        
    
# ================= ROB =================
    
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ❌ OWNER PROTECTION: Agar reply kiya gaya user OWNER hai
    if update.message.reply_to_message and is_owner_user(update.message.reply_to_message.from_user.id):
        await update.message.reply_text(
            "👑 Stop right there!\n"
            "Ye koi normal cat nahi 😼\n"
            "✨ This is the OWNER of the bot.\n"
            "⚠️ Tumhari robbery yahin fail hoti hai.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if update.effective_chat.type == "private":
        return await update.message.reply_text("❌ Rob works in groups only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("❗ Reply to a cat and use /rob <amount>")

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text("💸 Use like: /rob <amount>")

    if amount < 1 or amount > 1000:
        return await update.message.reply_text("❗ You can only rob between 1 - 1000.")

    thief_user = update.effective_user
    victim_user = update.message.reply_to_message.from_user

    if victim_user.id == thief_user.id:
        return await update.message.reply_text("🙀 You can't rob yourself!")

    if victim_user.is_bot:
        return await update.message.reply_text("🤖 That's a bot!")

    thief = get_cat(thief_user)
    victim = get_cat(victim_user)

    # Clickable mentions
    thief_mention = f"<a href='tg://user?id={thief_user.id}'>{thief_user.first_name}</a>"
    victim_mention = f"<a href='tg://user?id={victim_user.id}'>{victim_user.first_name}</a>"

    # 👑 VIP SHIELD CHECK
    if victim["inventory"].get("vip_shield", 0) > 0:
        victim["inventory"]["vip_shield"] -= 1
        cats.update_one({"_id": victim["_id"]}, {"$set": victim})
        return await update.message.reply_text(
            f"👑 VIP SHIELD activated! {victim_mention} blocked the robbery!",
            parse_mode="HTML"
        )

    # 🛡 NORMAL PROTECTION CHECK
    if is_protected(victim) or victim["inventory"].get("shield", 0) > 0:
        if thief["inventory"].get("shield_breaker", 0) > 0:
            thief["inventory"]["shield_breaker"] -= 1
            cats.update_one({"_id": thief["_id"]}, {"$set": thief})
            await update.message.reply_text("💣 Shield Breaker used! Protection destroyed!")
        else:
            return await update.message.reply_text(
                f"🛡 {victim_mention} is protected by a magic shield!",
                parse_mode="HTML"
            )

    steal = min(amount, victim["coins"])

    if steal <= 0:
        return await update.message.reply_text(
            f"😿 {victim_mention} is broke! Has $0",
            parse_mode="HTML"
        )

    if steal < amount:
        await update.message.reply_text(
            f"⚠️ {victim_mention} has only ${victim['coins']}! You stole ${steal} instead.",
            parse_mode="HTML"
        )

    victim["coins"] -= steal
    thief["coins"] += steal

    cats.update_one({"_id": thief["_id"]}, {"$set": thief})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    # ✅ Group success message with mentions
    await update.message.reply_text(
        f"😼 {thief_mention} robbed {victim_mention} and stole ${steal}!",
        parse_mode="HTML"
    )

    # 📩 DM to victim
    try:
        await context.bot.send_message(
            chat_id=victim_user.id,
            text=f"🚨 You were robbed by {thief_mention}!\n💸 Lost: ${steal}",
            parse_mode="HTML"
        )
    except:
        pass  # user may have DMs closed
        
# ================= /kill =================

async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ❌ OWNER PROTECTION: Agar target owner hai
    if update.message.reply_to_message and is_owner_user(update.message.reply_to_message.from_user.id):
        await update.message.reply_text(
            "👑 Hold up!\n"
            "Ye koi normal cat nahi 😼\n"
            "✨ This is the OWNER of the bot.\n"
            "⚠️ Tumhari command yahin khatam hoti hai.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to attack someone.")

    attacker_user = update.effective_user
    victim_user = update.message.reply_to_message.from_user

    # Khud ko attack na kar sake
    if attacker_user.id == victim_user.id:
        return await update.message.reply_text("You can't attack yourself 😹")

    attacker = get_cat(attacker_user)
    victim = get_cat(victim_user)

    # Clickable mentions
    attacker_mention = f"<a href='tg://user?id={attacker_user.id}'>{attacker_user.first_name}</a>"
    victim_mention = f"<a href='tg://user?id={victim_user.id}'>{victim_user.first_name}</a>"

    # 🛡 PROTECTION CHECK
    if victim["inventory"].get("vip_shield", 0) > 0:
        return await update.message.reply_text(
            f"👑 {victim_mention} is protected by a VIP Shield!",
            parse_mode="HTML"
        )

    if victim["inventory"].get("shield", 0) > 0 or is_protected(victim):
        return await update.message.reply_text(
            f"🛡 {victim_mention} is protected right now!",
            parse_mode="HTML"
        )

    # 🪦 Already dead check
    if victim.get("health", 100) <= 0:
        return await update.message.reply_text(
            f"☠️ {victim_mention} is already dead!\nNo need to attack again 😼",
            parse_mode="HTML"
        )

    # 🎁 Reward
    reward = random.randint(80, 160)

    attacker["kills"] += 1
    victim["deaths"] += 1
    attacker["coins"] += reward

    # Victim health zero
    victim["health"] = 0

    cats.update_one({"_id": attacker["_id"]}, {"$set": attacker})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    # ✅ Group message
    await update.message.reply_text(
        f"⚔️ {attacker_mention} attacked {victim_mention} and won!\n"
        f"💰 Reward: ${reward}",
        parse_mode="HTML"
    )

    # 📩 DM to victim
    try:
        await context.bot.send_message(
            chat_id=victim_user.id,
            text=(
                f"🚨 <b>You were attacked!</b>\n"
                f"⚔️ Attacker: {attacker_mention}\n"
                f"💀 You lost the fight and are now dead.\n"
                f"❤️ Health: 0"
            ),
            parse_mode="HTML"
        )
    except:
        pass
        
# ================= PROTECTION COMMAND =================

async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    now = datetime.now(timezone.utc)

    # ❗ Show usage if no argument
    if not context.args:
        return await update.message.reply_text("⚠️ Usage: /protection 1d")

    # ❌ Only 1d allowed
    if context.args[0].lower() != "1d":
        return await update.message.reply_text("❗ Users can only use: 1d")

    # 🛡 Already protected check
    protected_until = cat.get("protected_until")
    if protected_until and protected_until.tzinfo is None:
        protected_until = protected_until.replace(tzinfo=timezone.utc)

    if protected_until and protected_until > now:
        remaining = protected_until - now
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        days = remaining.days

        time_text = ""
        if days > 0:
            time_text += f"{days}d "
        if hours > 0:
            time_text += f"{hours}h "
        if minutes > 0:
            time_text += f"{minutes}m"

        return await update.message.reply_text(
            f"🛡 You are already protected!\n⏳ Time left: {time_text.strip()}"
        )

    # 💰 Cost check
    cost = 600
    if cat["coins"] < cost:
        return await update.message.reply_text(f"Need ${cost} for protection.")

    # ✅ Activate protection
    cat["coins"] -= cost
    cat["protected_until"] = now + timedelta(days=1)

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})

    await update.message.reply_text("🛡 Protection enabled for 1 day.")
    
# ================= BUTTONS =================
def leaderboard_buttons():
    keyboard = [[
        InlineKeyboardButton("🏆 Richest Cats", callback_data="lb_rich"),
        InlineKeyboardButton("⚔️ Top Fighters", callback_data="lb_kill"),
    ]]
    return InlineKeyboardMarkup(keyboard)

# ================= RANK BADGES =================
def rank_decor(rank: int) -> str:
    return ["👑", "🥈", "🥉"][rank-1] if rank <= 3 else "🎖"

# ================= RANK MOVEMENT =================
def get_rank_arrow(user_id: int, board_type: str, new_rank: int) -> str:
    key = f"{board_type}_{user_id}"
    prev = leaderboard_history.find_one({"_id": key})

    if not prev:
        leaderboard_history.insert_one({"_id": key, "rank": new_rank})
        return "🆕"

    old_rank = prev["rank"]
    leaderboard_history.update_one({"_id": key}, {"$set": {"rank": new_rank}})

    if new_rank < old_rank:
        return "🔼"
    elif new_rank > old_rank:
        return "🔽"
    return "➖"

# ================= BUILD RICH BOARD =================
def build_rich_board():
    top = cats.find().sort("coins", -1).limit(10)
    msg = "<b>🏆 Top Rich Cats</b>\n\n"

    for i, c in enumerate(top, 1):
        user_id = c["_id"]
        name = c.get("name", "Cat")
        coins = c.get("coins", 0)

        badge = rank_decor(i)
        arrow = get_rank_arrow(user_id, "rich", i)
        mention = f"<a href='tg://user?id={user_id}'>{name}</a>"

        msg += f"{badge} {i}. {mention} {arrow} — ${coins}\n"

    return msg

# ================= BUILD KILL BOARD =================
def build_kill_board():
    top = cats.find().sort("kills", -1).limit(10)
    msg = "<b>⚔️ Top Fighters</b>\n\n"

    for i, c in enumerate(top, 1):
        user_id = c["_id"]
        name = c.get("name", "Cat")
        kills = c.get("kills", 0)

        badge = rank_decor(i)
        arrow = get_rank_arrow(user_id, "kill", i)
        mention = f"<a href='tg://user?id={user_id}'>{name}</a>"

        msg += f"{badge} {i}. {mention} {arrow} — {kills} wins\n"

    return msg

# ================= COMMANDS =================
async def toprich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_rich_board()
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_buttons()
    )

async def topkill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_kill_board()
    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_buttons()
    )

# ================= BUTTON SWITCH =================
async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "lb_rich":
        msg = build_rich_board()
    else:
        msg = build_kill_board()

    await query.edit_message_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_buttons()
    )

# ================= /me Command =================
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    cat = get_cat(target_user)

    # 👑 OWNER PROFILE (GOD MODE)
    if is_owner_user(target_user.id):
        # Owner ke liye stats hardcode + infinite coins
        mention = f"<a href='tg://user?id={target_user.id}'>{target_user.first_name}</a>"
        await update.message.reply_text(
            f"👑 {mention} — <b>CATVERSE OWNER</b>\n\n"
            f"<b>🐾 Level:</b> 👑 Legend Cat\n"
            f"<b>💰 Money:</b> ∞\n"
            f"<b>🏆 Rank:</b> #∞\n"
            f"<b>🐟 Fish:</b> ∞\n"
            f"<b>⚔️ Wins:</b> ∞ | <b>💀 Deaths:</b> 0\n\n"
            f"<b>DNA →</b> 😼 100 | 🧠 100 | 🍀 100 | 💖 100\n"
            f"✨ <i>The one who rules Catverse</i>",
            parse_mode="HTML"
        )
        return

    # 🐱 Normal users
    d = cat["dna"]
    rank = calculate_global_rank(cat["_id"])
    mention = f"<a href='tg://user?id={target_user.id}'>{target_user.first_name}</a>"

    # Agar owner ne recently /lobu ya /give se coins diye, wo DB me update ho chuke honge, yahan latest show hoga
    await update.message.reply_text(
        f"🐾 {mention} — \n\n<b>🐾 Level:</b> {cat['level']}\n"
        f"<b>💰 Money:</b> ${cat['coins']}\n"
        f"<b>🏆 Rank:</b> #{rank}\n"
        f"<b>🐟 Fish:</b> {cat['fish']}\n"
        f"<b>⚔️ Wins:</b> {cat['kills']} | <b>💀 Deaths:</b> {cat['deaths']}\n\n"
        f"<b>DNA →</b> 😼 {d['aggression']} | 🧠 {d['intelligence']} | 🍀 {d['luck']} | 💖 {d['charm']}",
        parse_mode="HTML"
    )

# ================= /lobu Command =================
async def lobu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_user(update.effective_user.id):
        return await update.message.reply_text(
            "🚫 Sorry! Only the OWNER can use this command!"
        )

    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text(
            "Usage: /lobu <amount> (reply to a user)"
        )

    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text("❌ Enter a valid number!")

    # Target user
    target_user = update.message.reply_to_message.from_user
    target = get_cat(target_user)

    # Owner coins = infinite
    cat_owner = get_cat(update.effective_user)
    cat_owner["coins"] = float("inf")
    cats.update_one({"_id": cat_owner["_id"]}, {"$set": cat_owner})  # ✅ update DB

    # Add coins to target user
    target["coins"] += amount
    cats.update_one({"_id": target["_id"]}, {"$set": target})  # ✅ update DB

    mention = f"<a href='tg://user?id={target_user.id}'>{target_user.first_name}</a>"
await update.message.reply_text(
    f"👑 Owner Power Activated!\n\n"
    f"✨ {mention} just received ${amount} instantly!\n"
    f"💰 Owner's magic never fails!",
    parse_mode="HTML"  # ✅ HTML mode for clickable mentions
)
    
# ================= FUN COMMAND =================

async def fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responses = [
        "😹 You found a hidden treasure! +$120",
        "🐟 A fish jumps into your inventory! +1 fish",
        "💤 You took a nap, nothing happened...",
        "🍀 Lucky day! Gain +2 luck",
        "😼 Mischievous cat almost stole your money!",
    ]
    msg = random.choice(responses)
    cat = get_cat(update.effective_user)

    if "$120" in msg:
        cat["coins"] += 120
    if "fish" in msg:
        cat["fish"] += 1
    if "luck" in msg:
        cat["dna"]["luck"] += 2

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(msg)

# ================= UPGRADE =================

UPGRADE_COSTS = {
    "aggression": 150,
    "intelligence": 150,
    "luck": 220,
    "charm": 220,
}

async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Usage: /upgrade <stat> <amount>\nStats: aggression, intelligence, luck, charm"
        )

    cat = get_cat(update.effective_user)
    stat = context.args[0].lower()
    amount = int(context.args[1]) if len(context.args) > 1 else 1

    if stat not in UPGRADE_COSTS:
        return await update.message.reply_text("❌ Invalid stat!")

    cost = UPGRADE_COSTS[stat] * amount
    if cat["coins"] < cost:
        return await update.message.reply_text(f"❌ Not enough money! Costs ${cost}")

    cat["coins"] -= cost
    cat["dna"][stat] += amount
    evolve(cat)
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})

    await update.message.reply_text(
        f"✅ {stat.capitalize()} increased by {amount}! Spent ${cost}\n"
        f"New {stat.capitalize()}: {cat['dna'][stat]}\n"
        f"Current Level: {cat['level']}"
    )

#  ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("games", games))
    app.add_handler(CommandHandler("xp", xp))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("lobu", lobu))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("bal", bal))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("gift", gift))
    app.add_handler(CommandHandler("use", use))
    app.add_handler(CallbackQueryHandler(shop_system, pattern="shop|giftshop"))
    app.add_handler(CommandHandler("rob", rob))
    app.add_handler(CommandHandler("fish", fish))
    app.add_handler(CommandHandler("moon_mere_papa", moon_mere_papa))
    app.add_handler(CommandHandler("kill", kill))
    app.add_handler(CommandHandler("protect", protect))
    app.add_handler(CommandHandler("toprich", toprich))
    app.add_handler(CommandHandler("topkill", topkill))
    app.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^lb_"))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CallbackQueryHandler(shop_system, pattern="^shop:"))
    app.add_handler(CommandHandler("fun", fun))
    app.add_handler(CommandHandler("upgrade", upgrade))
    app.add_handler(CommandHandler("fishlb", fishlb))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_chat))

    print("ðŸ± CATVERSE FULLY UPGRADED & RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
