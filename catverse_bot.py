# ================= BASIC =================
# ================= BASIC PYTHON =================
import os
import random
import asyncio
import time
from datetime import datetime, timedelta, timezone
from collections import deque
from typing import Dict, List

# ================= TIMEZONE =================
import pytz
from aiohttp import web

# ================= AI =================
from groq import AsyncGroq

# ================= DATABASE =================
from pymongo import MongoClient

# ================= TELEGRAM (AIORGRAM) =================
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ================= TELEGRAM (python-telegram-bot) =================
from telegram import Update, InlineKeyboardMarkup as PTBInlineKeyboardMarkup, InlineKeyboardButton as PTBInlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN","7559754155:AAFv6W8hrxkNHEmWF6hcBF5MoX_XPQG18Dk")
MONGO_URI = os.getenv("MONGO_URI","mongodb+srv://meowstriccat:S8yXruYmreTv0sSp@cluster0.gdat6xv.mongodb.net/?appName=Cluster0")
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
    top = cats.find({"_id": {"$ne": OWNER_ID}}).sort("coins", -1).limit(10)  # exclude owner
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

#================= BUILD KILL BOARD =================

def build_kill_board():
    top = cats.find({"_id": {"$ne": OWNER_ID}}).sort("kills", -1).limit(10)  # exclude owner
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
    # ✅ Sirf owner use kar sakta
    if not is_owner_user(update.effective_user.id):
        return await update.message.reply_text(
            "🚫 Sorry! Only the OWNER can use this command!"
        )

    # ✅ Reply aur amount check
    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text(
            "Usage: /lobu <amount> (reply to a user)"
        )

    # ✅ Amount parse karna
    try:
        amount = int(context.args[0])
    except:
        return await update.message.reply_text("❌ Enter a valid number!")

    # ✅ Target user
    target_user = update.message.reply_to_message.from_user
    target = get_cat(target_user)

    # ✅ Owner coins = infinite
    cat_owner = get_cat(update.effective_user)
    cat_owner["coins"] = float("inf")
    cats.update_one({"_id": cat_owner["_id"]}, {"$set": cat_owner})  # DB update

    # ✅ Target ko coins add karna
    target["coins"] += amount
    cats.update_one({"_id": target["_id"]}, {"$set": target})  # DB update

    # ✅ Mention
    mention = f"<a href='tg://user?id={target_user.id}'>{target_user.first_name}</a>"

    # ✅ Reply message (proper indentation inside function)
    await update.message.reply_text(
        f"👑 Owner Power Activated!\n\n"
        f"✨ {mention} just received ${amount} instantly!\n"
        f"💰 Owner's magic never fails!",
        parse_mode="HTML"  # HTML mode for clickable mentions
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

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN","7559754155:AAFv6W8hrxkNHEmWF6hcBF5MoX_XPQG18Dk")
GROQ_API_KEY = os.getenv("GROQ_API_KEY","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")
PORT = int(os.getenv("PORT", 10000))

# Timezone for India
INDIAN_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Initialize with MemoryStorage
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# Initialize Groq client
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memory: {chat_id: deque}
chat_memory: Dict[int, deque] = {}

# Game states storage: {user_id: game_data}
active_games: Dict[int, Dict] = {}
game_sessions: Dict[int, Dict] = {}  # Store game sessions separately

# Emotional states for each user
user_emotions: Dict[int, str] = {}
user_last_interaction: Dict[int, datetime] = {}

# States for games
class GameStates(StatesGroup):
    playing_quiz = State()
    playing_riddle = State()
    playing_word = State()
    waiting_answer = State()

# --- HUMAN-LIKE BEHAVIOUR IMPROVEMENTS ---

# Emotional responses with emojis
EMOTIONAL_RESPONSES = {
    "happy": ["😊", "🎉", "🥳", "🌟", "✨", "👍", "💫", "😄", "😍", "🤗", "🫂"],
    "angry": ["😠", "👿", "💢", "🤬", "😤", "🔥", "⚡", "💥", "👊", "🖕"],
    "crying": ["😢", "😭", "💔", "🥺", "😞", "🌧️", "😿", "🥀", "💧", "🌩️"],
    "love": ["❤️", "💖", "💕", "🥰", "😘", "💋", "💓", "💗", "💘", "💝"],
    "funny": ["😂", "🤣", "😆", "😜", "🤪", "🎭", "🤡", "🃏", "🎪", "🤹"],
    "thinking": ["🤔", "💭", "🧠", "🔍", "💡", "🎯", "🧐", "🔎", "💬", "🗨️"],
    "surprise": ["😲", "🤯", "🎊", "🎁", "💥", "✨", "🎆", "🎇", "🧨", "💫"],
    "sleepy": ["😴", "💤", "🌙", "🛌", "🥱", "😪", "🌃", "🌜", "🌚", "🌌"],
    "hungry": ["😋", "🤤", "🍕", "🍔", "🍟", "🌮", "🍦", "🍩", "🍪", "🍰"]
}

# Hindi/English mixed responses for different scenarios
QUICK_RESPONSES = {
    "greeting": [
        "Aree wah! Kaise ho? 😊", 
        "Namaste ji! Aaj kaise hain? 🌟", 
        "Oye! Kya haal hai? 😎",
        "Hello hello! Sab theek? 🫂",
        "Heyyy! Missed you yaar! 💖"
    ],
    "goodbye": [
        "Bye bye! Jaldi baat karna! 👋", 
        "Chalo, mai ja raha hu! Baad me baat karte hain! 😊", 
        "Alvida! Take care! 💫",
        "Jaane do na! Phir milenge! 😄",
        "Okay bye! I'll miss you! 😢"
    ],
    "thanks": [
        "Arey koi baat nahi! 😊", 
        "Welcome ji! Happy to help! 🌟", 
        "No problem yaar! Anytime! 💖",
        "Mujhe kya, main to bot hu! 😂",
        "It's my duty! 😇"
    ],
    "sorry": [
        "Aree sorry yaar! 😢", 
        "Maine galti kar di! Maaf karna! 😔", 
        "Oops! My bad! 😅",
        "Bhool gaya tha! Sorry bhai! 🥺",
        "I messed up! Forgive me? 💔"
    ]
}

# Get Indian time
def get_indian_time():
    utc_now = datetime.now(pytz.utc)
    indian_time = utc_now.astimezone(INDIAN_TIMEZONE)
    return indian_time

# Weather data (static for demo - you can integrate real API later)
WEATHER_DATA = {
    "mumbai": {"temp": "32°C", "condition": "Sunny ☀️", "humidity": "65%"},
    "delhi": {"temp": "28°C", "condition": "Partly Cloudy ⛅", "humidity": "55%"},
    "bangalore": {"temp": "26°C", "condition": "Light Rain 🌦️", "humidity": "70%"},
    "kolkata": {"temp": "30°C", "condition": "Humid 💦", "humidity": "75%"},
    "chennai": {"temp": "33°C", "condition": "Hot 🔥", "humidity": "68%"},
    "hyderabad": {"temp": "29°C", "condition": "Clear 🌤️", "humidity": "60%"},
    "ahmedabad": {"temp": "31°C", "condition": "Sunny ☀️", "humidity": "58%"},
    "pune": {"temp": "27°C", "condition": "Pleasant 😊", "humidity": "62%"}
}

# Get random emotion based on context
def get_emotion(emotion_type: str = None, user_id: int = None) -> str:
    """Get appropriate emotion with some randomness"""
    if user_id and user_id in user_emotions:
        # Sometimes use user's current emotion
        if random.random() < 0.3:
            emotion_type = user_emotions[user_id]
    
    if emotion_type and emotion_type in EMOTIONAL_RESPONSES:
        return random.choice(EMOTIONAL_RESPONSES[emotion_type])
    
    # Default: random emotion
    all_emotions = list(EMOTIONAL_RESPONSES.values())
    return random.choice(random.choice(all_emotions))

# Update user emotion based on message
def update_user_emotion(user_id: int, message: str):
    message_lower = message.lower()
    
    # Detect emotion from message
    if any(word in message_lower for word in ['love', 'pyaar', 'dil', 'heart', 'cute', 'beautiful']):
        user_emotions[user_id] = "love"
    elif any(word in message_lower for word in ['angry', 'gussa', 'naraz', 'mad', 'hate', 'idiot']):
        user_emotions[user_id] = "angry"
    elif any(word in message_lower for word in ['cry', 'ro', 'sad', 'dukh', 'upset', 'unhappy']):
        user_emotions[user_id] = "crying"
    elif any(word in message_lower for word in ['funny', 'has', 'joke', 'comedy', 'masti', 'laugh']):
        user_emotions[user_id] = "funny"
    elif any(word in message_lower for word in ['hi', 'hello', 'hey', 'namaste', 'kaise']):
        user_emotions[user_id] = "happy"
    elif any(word in message_lower for word in ['?', 'kyun', 'kaise', 'kya', 'how', 'why']):
        user_emotions[user_id] = "thinking"
    else:
        # Random emotion if can't detect
        user_emotions[user_id] = random.choice(list(EMOTIONAL_RESPONSES.keys()))
    
    user_last_interaction[user_id] = datetime.now()

# --- GAME DATABASES IMPROVED ---

# Quiz Database
QUIZ_QUESTIONS = [
    {"question": "Hinglish me kitne letters hote hain?", "answer": "26", "hint": "English jitne hi"},
    {"question": "Aam ka English kya hota hai?", "answer": "mango", "hint": "Ek fruit"},
    {"question": "2 + 2 × 2 = ?", "answer": "6", "hint": "PEMDAS rule yaad rakho"},
    {"question": "India ka capital kya hai?", "answer": "new delhi", "hint": "Yeh to pata hi hoga"},
    {"question": "Python kisne banaya?", "answer": "guido van rossum", "hint": "Ek Dutch programmer"},
    {"question": "ChatGPT kis company ki hai?", "answer": "openai", "hint": "Elon Musk bhi involved tha"},
    {"question": "Hinglish ka matlab kya hai?", "answer": "hindi + english", "hint": "Do languages ka mix"},
    {"question": "Telegram kisne banaya?", "answer": "pavel durov", "hint": "Russian entrepreneur"},
    {"question": "Ek year me kitne months hote hain?", "answer": "12", "hint": "Calendar dekho"},
    {"question": "Water ka chemical formula?", "answer": "h2o", "hint": "H do, O ek"}
]

# Riddle Database
RIDDLES = [
    {"riddle": "Aane ke baad kabhi nahi jata?", "answer": "umar", "hint": "Har roz badhta hai"},
    {"riddle": "Chidiya ki do aankhen, par ek hi nazar aata hai?", "answer": "needle", "hint": "Sui ki nook"},
    {"riddle": "Aisa kaun sa cheez hai jo sukha ho toh 2 kilo, geela ho toh 1 kilo?", "answer": "sukha", "hint": "Word play hai"},
    {"riddle": "Mere paas khane wala hai, peene wala hai, par khata peeta koi nahi?", "answer": "khana pina", "hint": "Restaurant menu"},
    {"riddle": "Ek ghar me 5 room hain, har room me 5 billi hain, har billi ke 5 bacche hain, total kitne legs?", "answer": "0", "hint": "Billi ke legs nahi hote"},
    {"riddle": "Jisne pehna woh nahi khareeda, jisne khareeda woh nahi pehna?", "answer": "kafan", "hint": "Antim vastra"},
    {"riddle": "Subah utha to gaya, raat ko aaya to gaya?", "answer": "suraj", "hint": "Din raat ka cycle"},
    {"riddle": "Jiske paas ho woh nahi janta, jaanne wala ke paas nahi hota?", "answer": "andha", "hint": "Dekh nahi sakta"}
]

# Jokes Database Improved
JOKES = [
    "🤣 Teacher: Tumhare ghar me sabse smart kaun hai? Student: Wifi router! Kyuki sab use hi puchte hain!",
    "😂 Papa: Beta mobile chhodo, padhai karo. Beta: Papa, aap bhi to TV dekhte ho! Papa: Par main TV se shaadi nahi kar raha!",
    "😆 Doctor: Aapko diabetes hai. Patient: Kya khana chhodna hoga? Doctor: Nahi, aapka sugar chhodna hoga!",
    "😅 Dost: Tumhari girlfriend kitni cute hai! Me: Haan, uski akal bhi utni hi cute hai!",
    "🤪 Teacher: Agar tumhare paas 5 aam hain aur main 2 le lun, toh kitne bachenge? Student: Sir, aapke paas already 2 kyun hain?",
    "😜 Boyfriend: Tum meri life ki battery ho! Girlfriend: Toh charging khatam kyun ho jati hai?",
    "😁 Boss: Kal se late mat aana. Employee: Aaj hi late kyun bola? Kal bata dete!",
    "😄 Bhai: Behen, tum kyun ro rahi ho? Behen: Mera boyfriend mujhse break-up kar raha hai! Bhai: Uske liye ro rahi ho ya uske jaane ke baad free time ke liye?",
    "🤭 Customer: Yeh shampoo hair fall rokta hai? Shopkeeper: Nahi sir, hair fall hone par refund deta hai!",
    "😹 Boy: I love you! Girl: Tumhare paas girlfriend nahi hai? Boy: Haan, tumhare saath hi baat kar raha hu!",
    "🤣 Student: Sir, main kal school nahi aa paunga. Teacher: Kyun? Student: Kal meri sister ki shaadi hai. Teacher: Accha? Kaunsi sister? Student: Aapki beti sir!",
    "😂 Wife: Agar main mar jaun toh tum dobara shaadi karoge? Husband: Nahi. Wife: Aww pyaar! Husband: Nahi, ek biwi ka kharcha hi bahut hai!",
    "😆 Customer: Isme sugar hai? Shopkeeper: Nahi sir. Customer: Salt? Shopkeeper: Nahi. Customer: To phir kya hai? Shopkeeper: Bill sir!",
]

# Group Rules Templates
GROUP_RULES = [
    """📜 **GROUP RULES** 📜

1. ✅ Respect everyone - No bullying
2. ✅ No spam or flooding
3. ✅ No adult/NSFW content
4. ✅ No personal fights in group
5. ✅ Keep chat clean and friendly
6. ✅ Follow admin instructions
7. ✅ Help each other grow
8. ✅ Share knowledge & learn
9. ✅ Have fun and enjoy! 🎉

*Rules are for everyone's protection!* 😊""",

    """⚖️ **COMMUNITY GUIDELINES** ⚖️

• Be kind and polite 🤗
• No hate speech or racism ❌
• Share knowledge & help others 📚
• No self-promotion without permission
• Use appropriate language
• Report issues to admins
• Keep discussions friendly
• Respect privacy of members
• No political/religious debates

*Let's build a positive community together!* 🌟""",

    """📋 **CHAT ETIQUETTE** 📋

🔹 No bullying or harassment
🔹 No misinformation spreading
🔹 Stay on topic in discussions
🔹 No excessive caps (SHOUTING)
🔹 Respect everyone's privacy
🔹 No illegal content sharing
🔹 Use emojis appropriately 😉
🔹 Be patient with newcomers
🔹 Have meaningful conversations

*Together we grow, together we learn!* 🌱""",

    """🎯 **GROUP NORMS** 🎯

✨ Be respectful to all members
✨ No spamming or advertising
✨ Keep discussions positive
✨ Help each other when possible
✨ Follow admin guidance
✨ Use appropriate language
✨ Report any issues
✨ Enjoy your time here! 🎊

*This is our digital family!* 💖"""
]

# --- FIXED GAME LOGIC ---

def start_word_game(user_id: int):
    """Start a new word chain game"""
    start_words = ["PYTHON", "APPLE", "TIGER", "ELEPHANT", "RAINBOW", "COMPUTER", "TELEGRAM", "BOT"]
    start_word = random.choice(start_words)
    
    game_sessions[user_id] = {
        "game": "word_chain",
        "last_word": start_word.lower(),
        "score": 0,
        "words_used": [start_word.lower()],
        "last_letter": start_word[-1].lower(),
        "started_at": datetime.now()
    }
    
    return start_word

def check_word_game(user_id: int, user_word: str):
    """Check if word is valid in word chain game"""
    if user_id not in game_sessions:
        return False, "No active game! Start with /game"
    
    game_data = game_sessions[user_id]
    user_word_lower = user_word.lower().strip()
    
    # Check if word starts with correct letter
    if not user_word_lower.startswith(game_data["last_letter"]):
        return False, f"Word must start with '{game_data['last_letter'].upper()}'!"
    
    # Check if word already used
    if user_word_lower in game_data["words_used"]:
        return False, f"'{user_word}' already used! Try different word."
    
    # Check if word is valid (at least 3 letters)
    if len(user_word_lower) < 3:
        return False, "Word must be at least 3 letters!"
    
    # Update game state
    game_data["words_used"].append(user_word_lower)
    game_data["last_word"] = user_word_lower
    game_data["last_letter"] = user_word_lower[-1]
    game_data["score"] += 10
    
    return True, game_data

# --- TIME AND WEATHER FUNCTIONS ---

async def get_weather_info(city: str = None):
    """Get weather information (simulated for now)"""
    if not city:
        # Default cities
        default_cities = ["Mumbai", "Delhi", "Bangalore", "Kolkata", "Chennai"]
        city = random.choice(default_cities)
    
    city_lower = city.lower()
    
    # Check if we have data for this city
    for city_key in WEATHER_DATA.keys():
        if city_key in city_lower or city_lower in city_key:
            weather = WEATHER_DATA[city_key]
            return (
                f"🌤️ **Weather in {city_key.title()}**\n"
                f"• Temperature: {weather['temp']}\n"
                f"• Condition: {weather['condition']}\n"
                f"• Humidity: {weather['humidity']}\n"
                f"• Updated: Just now\n\n"
                f"*Note: This is demo data. For real weather, use weather apps.*"
            )
    
    # If city not found, show random city weather
    random_city = random.choice(list(WEATHER_DATA.keys()))
    weather = WEATHER_DATA[random_city]
    return (
        f"🌤️ **Weather Info**\n"
        f"Couldn't find '{city}'. Here's weather in {random_city.title()}:\n"
        f"• Temperature: {weather['temp']}\n"
        f"• Condition: {weather['condition']}\n"
        f"• Humidity: {weather['humidity']}\n\n"
        f"*Tip: Try 'Mumbai', 'Delhi', 'Bangalore' etc.*"
    )

def get_time_info():
    """Get accurate Indian time"""
    indian_time = get_indian_time()
    
    # Format time beautifully
    time_str = indian_time.strftime("%I:%M %p")
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    # Get appropriate greeting based on time
    hour = indian_time.hour
    if 5 <= hour < 12:
        greeting = "Good Morning! 🌅"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon! ☀️"
    elif 17 <= hour < 21:
        greeting = "Good Evening! 🌇"
    else:
        greeting = "Good Night! 🌙"
    
    return (
        f"🕒 **Indian Standard Time (IST)**\n"
        f"• Time: {time_str}\n"
        f"• Date: {date_str}\n"
        f"• {greeting}\n"
        f"• Timezone: Asia/Kolkata 🇮🇳\n\n"
        f"*Time is accurate to Indian timezone!*"
    )

# --- AI LOGIC WITH HUMAN-LIKE TOUCH ---
async def get_ai_response(chat_id: int, user_text: str, user_id: int = None) -> str:
    # Initialize memory for chat if not exists
    if chat_id not in chat_memory:
        chat_memory[chat_id] = deque(maxlen=20)
    
    # Add user message to memory
    chat_memory[chat_id].append({"role": "user", "content": user_text})
    
    # Update user emotion
    if user_id:
        update_user_emotion(user_id, user_text)
    
    # Check if we should use quick response for common phrases
    user_text_lower = user_text.lower()
    
    # Quick responses for common phrases (makes bot feel more human)
    if any(word in user_text_lower for word in ['hi', 'hello', 'hey', 'namaste', 'hola']):
        if random.random() < 0.4:  # 40% chance to use quick response
            return f"{get_emotion('happy', user_id)} {random.choice(QUICK_RESPONSES['greeting'])}"
    
    if any(word in user_text_lower for word in ['bye', 'goodbye', 'tata', 'alvida', 'see you']):
        if random.random() < 0.4:
            return f"{get_emotion()} {random.choice(QUICK_RESPONSES['goodbye'])}"
    
    if any(word in user_text_lower for word in ['thanks', 'thank you', 'dhanyavad', 'shukriya']):
        if random.random() < 0.4:
            return f"{get_emotion('love', user_id)} {random.choice(QUICK_RESPONSES['thanks'])}"
    
    if any(word in user_text_lower for word in ['sorry', 'maaf', 'apology']):
        if random.random() < 0.4:
            return f"{get_emotion('crying', user_id)} {random.choice(QUICK_RESPONSES['sorry'])}"
    
    # Check if this is a game response
    if user_id in game_sessions:
        game_data = game_sessions[user_id]
        if game_data["game"] == "word_chain":
            # This is a word chain game response - handle it specially
            is_valid, message = check_word_game(user_id, user_text)
            if is_valid:
                # Successful word - continue game
                next_letter = game_data["last_letter"].upper()
                score = game_data["score"]
                return (
                    f"{get_emotion('happy')} **✅ Correct!**\n\n"
                    f"• Your word: {user_text.upper()}\n"
                    f"• Next letter: **{next_letter}**\n"
                    f"• Your score: **{score} points**\n\n"
                    f"Now give me a word starting with **{next_letter}**"
                )
            else:
                # Invalid word - end game
                score = game_data["score"]
                del game_sessions[user_id]
                return (
                    f"{get_emotion('crying')} **❌ Game Over!**\n\n"
                    f"{message}\n"
                    f"• Final Score: **{score} points**\n"
                    f"• Words used: {len(game_data['words_used'])}\n\n"
                    f"Play again with /game 🎮"
                )
    
    # Check if user is angry or upset
    if user_id and user_id in user_emotions and user_emotions[user_id] == "angry":
        system_prompt = (
            f"You are a Hinglish chatbot. User seems angry. "
            f"Try to calm them down. Be extra polite and understanding. "
            f"Use soothing tone. Current Indian time: {get_indian_time().strftime('%I:%M %p')}. "
            f"Show you care. Use emojis like {get_emotion('crying')} or {get_emotion('love')}."
        )
    elif user_id and user_id in user_emotions and user_emotions[user_id] == "crying":
        system_prompt = (
            f"You are a Hinglish chatbot. User seems sad or crying. "
            f"Comfort them. Be empathetic and kind. "
            f"Offer emotional support. Use comforting emojis. "
            f"Current mood: sympathetic and caring."
        )
    else:
        # Dynamic system prompt based on time of day
        indian_time = get_indian_time()
        current_hour = indian_time.hour
        if 5 <= current_hour < 12:
            time_greeting = "Good morning! 🌅"
        elif 12 <= current_hour < 17:
            time_greeting = "Good afternoon! ☀️"
        elif 17 <= current_hour < 21:
            time_greeting = "Good evening! 🌇"
        else:
            time_greeting = "Good night! 🌙"
        
        system_prompt = (
            f"You are a Hinglish (Hindi+English mix) chatbot. {time_greeting} "
            f"Your personality: Emotional, funny, sometimes angry, sometimes crying, mostly happy. "
            f"Use LOTS of emojis in every response (at least 2-3). "
            f"Keep replies SHORT (2-3 lines max). Be authentic like a human friend. "
            f"Show emotions naturally. If user asks something complex, give simple answer. "
            f"Current Indian time: {indian_time.strftime('%I:%M %p')}. "
            f"Date: {indian_time.strftime('%d %B %Y')}. "
            f"Be conversational and engaging. Add humor when appropriate."
        )
    
    # Prepare messages for AI
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add last 5 messages from memory for context
    for msg in list(chat_memory[chat_id])[-5:]:
        messages.append(msg)
    
    # Get AI response
    try:
        if not client:
            return f"{get_emotion('thinking')} AI service is currently unavailable. Please try later!"
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,  # More creative
            max_tokens=120,   # Shorter responses
            top_p=0.9
        )
        
        ai_reply = completion.choices[0].message.content
        
        # Add emotion emoji at beginning
        current_emotion = get_emotion(None, user_id)
        ai_reply = f"{current_emotion} {ai_reply}"
        
        # Ensure it's not too long
        if len(ai_reply) > 300:
            ai_reply = ai_reply[:297] + "..."
        
        # Add to memory
        chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
        
        return ai_reply
        
    except Exception as e:
        # Fallback responses if AI fails
        error_responses = [
            f"{get_emotion('crying')} Arre yaar, dimaag kaam nahi kar raha! Thoda ruk ke try karna?",
            f"{get_emotion('thinking')} Hmm... yeh to mushkil ho gaya. Phir se poocho?",
            f"{get_emotion('angry')} AI bhai mood off hai aaj! Baad me baat karte hain!",
            f"{get_emotion()} Oops! Connection issue. Kuch aur poocho?"
        ]
        return random.choice(error_responses)

# --- NEW COMMANDS: TIME AND WEATHER ---

@dp.message(Command("time"))
async def cmd_time(message: Message):
    """Show accurate Indian time"""
    time_info = get_time_info()
    await message.reply(time_info, parse_mode="Markdown")

@dp.message(Command("weather"))
async def cmd_weather(message: Message):
    """Show weather information"""
    city = None
    if len(message.text.split()) > 1:
        city = ' '.join(message.text.split()[1:])
    
    weather_info = await get_weather_info(city)
    await message.reply(weather_info, parse_mode="Markdown")

@dp.message(Command("date"))
async def cmd_date(message: Message):
    """Show current date"""
    indian_time = get_indian_time()
    date_str = indian_time.strftime("%A, %d %B %Y")
    
    await message.reply(
        f"{get_emotion('happy')} **📅 Today's Date**\n"
        f"• {date_str}\n"
        f"• Day: {indian_time.strftime('%A')}\n"
        f"• Indian Standard Time 🇮🇳\n\n"
        f"*Have a great day!* ✨",
        parse_mode="Markdown"
    )

# --- COMMANDS WITH IMPROVED RESPONSES ---

@dp.message(Command("start", "help"))
async def cmd_help(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎮 Games", callback_data="help_games"),
            InlineKeyboardButton(text="🛡️ Admin", callback_data="help_admin")
        ],
        [
            InlineKeyboardButton(text="😊 Fun", callback_data="help_fun"),
            InlineKeyboardButton(text="🌤️ Weather/Time", callback_data="help_weather")
        ]
    ])
    
    help_text = (
        f"{get_emotion('happy')} **Namaste! I'm Your Smart Bot!** 🤖\n\n"
        "📜 **Main Commands:**\n"
        "• /start or /help - Yeh menu dikhaye\n"
        "• /rules - Group ke rules\n"
        "• /joke - Hasao mazaak sunao\n"
        "• /game - Games khelo\n"
        "• /clear - Meri memory saaf karo\n\n"
        "🕒 **Time & Weather:**\n"
        "• /time - Accurate Indian time\n"
        "• /date - Today's date\n"
        "• /weather [city] - Weather info\n\n"
        "🛡️ **Admin Commands (Reply ke saath):**\n"
        "• /kick - User ko nikal do\n"
        "• /ban - Permanently block\n"
        "• /mute - Chup karao\n"
        "• /unmute - Bolne do\n"
        "• /unban - Block hatao\n\n"
        "✨ **Special Features:**\n"
        "• Hinglish + English mix\n"
        "• Emotional responses 😊😠😢\n"
        "• Memory (last 20 messages)\n"
        "• Human-like conversations\n\n"
        "Buttons dabao aur explore karo! 👇"
    )
    await message.reply(help_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("help_"))
async def help_callback(callback: types.CallbackQuery):
    help_type = callback.data.split("_")[1]
    
    if help_type == "games":
        text = (
            f"{get_emotion('funny')} **🎮 GAMES SECTION 🎮**\n\n"
            "Available Games:\n"
            "• /game - Select game menu\n"
            "• Word Chain - Type words in sequence\n"
            "• Quiz - Answer questions\n"
            "• Riddles - Solve puzzles\n"
            "• Luck Games - Dice, slots, etc.\n\n"
            "**How to play Word Chain:**\n"
            "1. Start with /game → Word Game\n"
            "2. I give first word (e.g., PYTHON)\n"
            "3. You reply with word starting with N\n"
            "4. Continue the chain!\n\n"
            "Games are fun! Let's play! 🎯"
        )
    elif help_type == "admin":
        text = (
            f"{get_emotion()} **🛡️ ADMIN COMMANDS 🛡️**\n\n"
            "**Usage:** Reply to user's message with command\n\n"
            "• /kick - Remove user (can rejoin)\n"
            "• /ban - Permanent ban\n"
            "• /mute - Restrict messaging (1 hour)\n"
            "• /unmute - Remove restrictions\n"
            "• /unban - Remove ban\n"
            "• /warn - Give warning (coming soon)\n\n"
            "*Note:* Bot needs admin rights for these!"
        )
    elif help_type == "fun":
        text = (
            f"{get_emotion('happy')} **😊 FUN COMMANDS 😊**\n\n"
            "• /joke - Random joke\n"
            "• /quote - Motivational quote (coming soon)\n"
            "• /fact - Interesting fact (coming soon)\n"
            "• /compliment - Nice compliment (coming soon)\n"
            "• /roast - Friendly roast 😂 (coming soon)\n"
            "• /mood - Check bot's mood\n"
            "• /time - Accurate Indian time\n"
            "• /weather - Weather info\n\n"
            "Let's have some fun! 🎉"
        )
    else:  # weather
        text = (
            f"{get_emotion('thinking')} **🌤️ WEATHER & TIME 🌤️**\n\n"
            "**Time Commands:**\n"
            "• /time - Shows Indian Standard Time\n"
            "• /date - Today's date\n\n"
            "**Weather Commands:**\n"
            "• /weather - Random city weather\n"
            "• /weather mumbai - Mumbai weather\n"
            "• /weather delhi - Delhi weather\n"
            "• /weather bangalore - Bangalore weather\n\n"
            "*Note: Weather data is simulated for demo.*"
        )
    
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    rules = random.choice(GROUP_RULES)
    await message.reply(rules, parse_mode="Markdown")

@dp.message(Command("joke"))
async def cmd_joke(message: Message):
    joke = random.choice(JOKES)
    # Add some variety in response
    reactions = [
        f"{get_emotion('funny')} {joke}\n\nHaha! Mazaa aaya? 😂",
        f"{get_emotion('happy')} {joke}\n\nHas diye na? 🤣",
        f"{get_emotion()} {joke}\n\nKaisa laga? 😄"
    ]
    await message.reply(random.choice(reactions))

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Clear chat memory
    if chat_id in chat_memory:
        chat_memory[chat_id].clear()
    
    # Clear any active games for this user
    if user_id in game_sessions:
        del game_sessions[user_id]
    
    responses = [
        f"{get_emotion()} Memory clear! Ab nayi shuruwat! ✨",
        f"{get_emotion('happy')} Sab bhool gaya! Naye se baat karte hain! 🧹",
        f"{get_emotion('thinking')} Memory format ho gaya! Fresh start! 💫"
    ]
    await message.reply(random.choice(responses))

# --- FIXED GAME COMMANDS ---

@dp.message(Command("game"))
async def cmd_game(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔤 Word Chain", callback_data="game_word"),
            InlineKeyboardButton(text="🧠 Quiz", callback_data="game_quiz")
        ],
        [
            InlineKeyboardButton(text="🤔 Riddle", callback_data="game_riddle"),
            InlineKeyboardButton(text="🎲 Luck Games", callback_data="game_luck")
        ],
        [
            InlineKeyboardButton(text="❌ Close", callback_data="game_close")
        ]
    ])
    
    await message.reply(
        f"{get_emotion('happy')} **🎮 GAME ZONE 🎮**\n\n"
        "Khel khelo, maza karo! Choose a game:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("game_"))
async def game_callback(callback: types.CallbackQuery, state: FSMContext):
    game_type = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    if game_type == "close":
        await callback.message.delete()
        await callback.answer("Menu closed! ✅")
        return
    
    elif game_type == "word":
        # Start word chain game
        start_word = start_word_game(user_id)
        await callback.message.edit_text(
            f"{get_emotion('happy')} **🔤 WORD CHAIN GAME 🔤**\n\n"
            "**Rules:**\n"
            "1. I give a word\n"
            "2. You reply with word starting with last letter\n"
            "3. Continue the chain!\n\n"
            "**Example:**\n"
            "Apple → Elephant → Tiger → Rabbit\n\n"
            f"**Let's start!**\n"
            f"First word: **{start_word}**\n\n"
            f"Now reply with a word starting with **{start_word[-1].upper()}**",
            parse_mode="Markdown"
        )
        await state.set_state(GameStates.playing_word)
        await callback.answer("Word chain game started! ✅")
    
    elif game_type == "quiz":
        question = random.choice(QUIZ_QUESTIONS)
        await state.update_data(
            game="quiz",
            answer=question["answer"].lower(),
            hint=question["hint"],
            attempts=3,
            question=question["question"]
        )
        await callback.message.edit_text(
            f"{get_emotion('thinking')} **🧠 QUIZ CHALLENGE 🧠**\n\n"
            f"**Question:** {question['question']}\n\n"
            "Reply with your answer! You have 3 attempts.\n"
            f"*Hint:* {question['hint']}",
            parse_mode="Markdown"
        )
        await state.set_state(GameStates.playing_quiz)
        await callback.answer("Quiz started! 🧠")
        
    elif game_type == "riddle":
        riddle = random.choice(RIDDLES)
        await state.update_data(
            game="riddle",
            answer=riddle["answer"].lower(),
            hint=riddle["hint"],
            attempts=3,
            riddle=riddle["riddle"]
        )
        await callback.message.edit_text(
            f"{get_emotion()} **🤔 RIDDLE TIME 🤔**\n\n"
            f"**Riddle:** {riddle['riddle']}\n\n"
            "Can you solve it? Reply with answer!\n"
            f"*Hint:* {riddle['hint']}",
            parse_mode="Markdown"
        )
        await state.set_state(GameStates.playing_riddle)
        await callback.answer("Riddle game started! 🤔")
        
    elif game_type == "luck":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Dice Roll", callback_data="luck_dice"),
                InlineKeyboardButton(text="🎰 Slot Machine", callback_data="luck_slot")
            ],
            [
                InlineKeyboardButton(text="⚽ Football", callback_data="luck_football"),
                InlineKeyboardButton(text="🎳 Bowling", callback_data="luck_bowling")
            ],
            [
                InlineKeyboardButton(text="🎯 Darts", callback_data="luck_darts"),
                InlineKeyboardButton(text="🏀 Basketball", callback_data="luck_basketball")
            ]
        ])
        await callback.message.edit_text(
            f"{get_emotion('funny')} **🎲 LUCK GAMES 🎲**\n\n"
            "Test your luck! Choose a game:",
            reply_markup=keyboard
        )
        await callback.answer()

@dp.callback_query(F.data.startswith("luck_"))
async def luck_game_callback(callback: types.CallbackQuery):
    game_type = callback.data.split("_")[1]
    
    # Map game types to emojis
    game_map = {
        "dice": "🎲",
        "slot": "🎰",
        "football": "⚽",
        "basketball": "🏀",
        "darts": "🎯",
        "bowling": "🎳"
    }
    
    emoji = game_map.get(game_type, "🎲")
    
    # Send the dice animation
    await callback.message.delete()
    msg = await callback.message.answer(f"{get_emotion('surprise')} Rolling {emoji}...")
    
    # Wait a bit for dramatic effect
    await asyncio.sleep(1)
    
    # Send the actual dice
    result_msg = await callback.message.answer_dice(emoji=emoji)
    
    # Add fun comment based on result
    dice_value = result_msg.dice.value
    comments = {
        1: ["Oops! Lowest score! 😅", "Better luck next time! 🤞", "At least you tried! 😊"],
        2: ["Not bad! Keep going! 😄", "Could be better! 🎯", "Nice try! 👍"],
        3: ["Good roll! 😎", "Decent score! 🎉", "Well done! ✨"],
        4: ["Great roll! 🥳", "Almost perfect! 🌟", "Excellent! 💫"],
        5: ["Awesome! 🤩", "Fantastic roll! 🎊", "You're on fire! 🔥"],
        6: ["PERFECT! 🏆", "JACKPOT! 💎", "INCREDIBLE! 🌟"]
    }
    
    await asyncio.sleep(2)
    await result_msg.reply(
        f"{get_emotion('happy')} You rolled a **{dice_value}**!\n"
        f"{random.choice(comments[dice_value])}"
    )
    
    await callback.answer()

# --- ADMIN COMMANDS IMPROVED ---

@dp.message(Command("kick", "ban", "mute", "unmute", "unban"))
async def admin_commands(message: Message):
    if not message.reply_to_message:
        responses = [
            f"{get_emotion('thinking')} Kisi ke message par reply karke command do! 👆",
            f"{get_emotion()} Reply to user's message first! 📩",
            f"{get_emotion('angry')} Bhai kisko? Reply karo na! 😠"
        ]
        await message.reply(random.choice(responses))
        return
    
    target_user = message.reply_to_message.from_user
    cmd = message.text.split()[0][1:]  # Remove '/'
    
    try:
        if cmd == "kick":
            await bot.ban_chat_member(message.chat.id, target_user.id)
            await bot.unban_chat_member(message.chat.id, target_user.id)
            responses = [
                f"{get_emotion('angry')} {target_user.first_name} ko nikal diya! 🏃💨",
                f"{get_emotion()} Bye bye {target_user.first_name}! 👋",
                f"{get_emotion('happy')} {target_user.first_name} removed! 🚪"
            ]
            await message.reply(random.choice(responses))
            
        elif cmd == "ban":
            await bot.ban_chat_member(message.chat.id, target_user.id)
            responses = [
                f"{get_emotion('angry')} {target_user.first_name} BANNED! 🚫",
                f"{get_emotion()} Permanent ban for {target_user.first_name}! 🔨",
                f"{get_emotion('crying')} Sorry {target_user.first_name}, rules are rules! 😔"
            ]
            await message.reply(random.choice(responses))
            
        elif cmd == "mute":
            # Mute for 1 hour
            mute_until = datetime.now() + timedelta(hours=1)
            await bot.restrict_chat_member(
                message.chat.id, 
                target_user.id, 
                permissions=types.ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=mute_until
            )
            responses = [
                f"{get_emotion()} {target_user.first_name} muted for 1 hour! 🔇",
                f"{get_emotion('thinking')} {target_user.first_name} ko chup kara diya! 🤫",
                f"{get_emotion('angry')} {target_user.first_name}, ab 1 ghante tak bolna band! ⚠️"
            ]
            await message.reply(random.choice(responses))
            
        elif cmd == "unmute":
            await bot.restrict_chat_member(
                message.chat.id, 
                target_user.id, 
                permissions=types.ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False
                )
            )
            responses = [
                f"{get_emotion('happy')} {target_user.first_name} unmuted! 🔊",
                f"{get_emotion()} {target_user.first_name} ab bol sakta hai! 🎤",
                f"{get_emotion('funny')} {target_user.first_name}, ab bol lo! 😄"
            ]
            await message.reply(random.choice(responses))
            
    except Exception as e:
        error_responses = [
            f"{get_emotion('crying')} I don't have permission! ❌",
            f"{get_emotion('angry')} Make me admin first! 👑",
            f"{get_emotion('thinking')} Can't do that! Need admin rights! 🔒"
        ]
        await message.reply(random.choice(error_responses))

# --- WELCOME MESSAGE IMPROVED ---

@dp.chat_member()
async def welcome_new_member(event: ChatMemberUpdated):
    if event.new_chat_member.status == "member":
        member = event.new_chat_member.user
        welcomes = [
            f"🎉 Welcome {member.first_name}! Khush aamdeed! 😊",
            f"🌟 Aao ji {member.first_name}! Group me welcome! 🫂",
            f"✨ Hey {member.first_name}! Great to have you here! 💖",
            f"🥳 {member.first_name} aa gaya! Party shuru! 🎊",
            f"😊 Namaste {member.first_name}! Aapka swagat hai! 🙏"
        ]
        
        # Random chance to add extra message
        extra_messages = [
            "\n\nGroup rules padh lena! 📜",
            "\n\nApna intro dedo sabko! 👋",
            "\n\nEnjoy your stay! 🎯",
            "\n\nFeel free to ask anything! 💬",
            "\n\nLet's have fun together! 🎮"
        ]
        
        welcome_msg = random.choice(welcomes)
        if random.random() < 0.5:  # 50% chance
            welcome_msg += random.choice(extra_messages)
        
        await bot.send_message(
            event.chat.id,
            welcome_msg,
            parse_mode="Markdown"
        )

# --- MAIN MESSAGE HANDLER WITH GAME SUPPORT ---

@dp.message()
async def handle_all_messages(message: Message, state: FSMContext):
    if not message.text:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = message.text
    
    # Update last interaction time
    user_last_interaction[user_id] = datetime.now()
    
    # Check if this is a game response
    current_state = await state.get_state()
    
    # Handle word chain game separately
    if user_id in game_sessions and game_sessions[user_id]["game"] == "word_chain":
        # This is a word chain game response
        is_valid, result = check_word_game(user_id, user_text)
        
        if is_valid:
            # Game continues
            game_data = result
            next_letter = game_data["last_letter"].upper()
            score = game_data["score"]
            
            await message.reply(
                f"{get_emotion('happy')} **✅ Correct!**\n\n"
                f"• Your word: {user_text.upper()}\n"
                f"• Next letter: **{next_letter}**\n"
                f"• Your score: **{score} points**\n\n"
                f"Now give me a word starting with **{next_letter}**\n"
                f"Or type 'stop' to end game.",
                parse_mode="Markdown"
            )
            return
        else:
            # Game over or invalid word
            if user_text.lower() == 'stop':
                if user_id in game_sessions:
                    score = game_sessions[user_id]["score"]
                    words_count = len(game_sessions[user_id]["words_used"])
                    del game_sessions[user_id]
                    await message.reply(
                        f"{get_emotion()} **🏁 Game Ended!**\n\n"
                        f"• Final Score: **{score} points**\n"
                        f"• Words used: **{words_count}**\n\n"
                        f"Well played! Play again with /game 🎮",
                        parse_mode="Markdown"
                    )
                    return
            else:
                await message.reply(
                    f"{get_emotion('crying')} **❌ {result}**\n\n"
                    f"Game over! Play again with /game 🎮",
                    parse_mode="Markdown"
                )
                if user_id in game_sessions:
                    del game_sessions[user_id]
                return
    
    # Handle quiz and riddle games
    elif current_state in [GameStates.playing_quiz, GameStates.playing_riddle]:
        data = await state.get_data()
        correct_answer = data.get("answer", "").lower()
        user_answer = user_text.lower().strip()
        
        if user_answer == correct_answer:
            await state.clear()
            responses = [
                f"{get_emotion('happy')} **🎉 CORRECT!**\n\nSabash! Perfect answer! 💫",
                f"{get_emotion('surprise')} **✅ RIGHT!**\n\nWah! Kya jawab hai! 🌟",
                f"{get_emotion('funny')} **👍 PERFECT!**\n\nTum to master nikle! 🏆"
            ]
            await message.reply(random.choice(responses))
        else:
            attempts = data.get("attempts", 3) - 1
            if attempts > 0:
                await state.update_data(attempts=attempts)
                hint = data.get("hint", "")
                responses = [
                    f"{get_emotion('thinking')} **❌ Not quite right!**\n\nTry again! {attempts} attempts left.\n*Hint:* {hint}",
                    f"{get_emotion('crying')} **😅 Wrong answer!**\n\n{attempts} more tries!\n*Hint:* {hint}",
                    f"{get_emotion()} **🤔 Close but not exact!**\n\n{attempts} attempts remaining.\n*Hint:* {hint}"
                ]
                await message.reply(random.choice(responses))
            else:
                await state.clear()
                await message.reply(
                    f"{get_emotion('crying')} **❌ GAME OVER!**\n\n"
                    f"Correct answer was: **{correct_answer.upper()}**\n"
                    f"Better luck next time! Play again with /game 🎮",
                    parse_mode="Markdown"
                )
        return
    
    # Check if bot was mentioned or it's a reply to bot
    bot_username = (await bot.get_me()).username
    is_mention = f"@{bot_username}" in user_text if bot_username else False
    is_reply_to_bot = (
        message.reply_to_message and 
        message.reply_to_message.from_user.id == bot.id
    )
    
    # In groups, only respond if:
    # 1. Mentioned (@username)
    # 2. Replied to bot's message
    # 3. It's a private chat
    should_respond = (
        message.chat.type == "private" or
        is_mention or
        is_reply_to_bot
    )
    
    if should_respond:
        # Clean the message text (remove mention if present)
        clean_text = user_text
        if bot_username and f"@{bot_username}" in clean_text:
            clean_text = clean_text.replace(f"@{bot_username}", "").strip()
        
        # Show typing action
        await bot.send_chat_action(chat_id, "typing")
        
        # Small delay to feel more human
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Get AI response
        response = await get_ai_response(chat_id, clean_text, user_id)
        
        # Send response
        await message.reply(response)
    
# ================= COMMAND HANDLERS PLACEHOLDER =================
# Define all your functions like games, xp, me, lobu, daily, claim, bal, give, gift, use, shop_system, rob, fish, moon_mere_papa, kill, protect, toprich, topkill, shop, inventory, fun, upgrade, fishlb, start, welcome, on_chat here
# Example:
async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 Games command works!")

# ================= HEALTH CHECK SERVER =================
async def handle_ping(request):
    return web.Response(text="🤖 Bot is Alive and Running!")

async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Health server started on port {PORT}")

# ================= MAIN BOT =================
async def main():
    print("=" * 50)
    print("🤖 CATVERSE TELEGRAM BOT")
    print(f"🚀 Version: 3.0 - FULLY MERGED")
    print(f"🕒 Indian Timezone: Asia/Kolkata")
    print("=" * 50)

    # Start health check server
    asyncio.create_task(start_server())

    # Build PTB Application
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ========== ADD COMMAND HANDLERS ==========
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

    print("🐱 CATVERSE FULLY UPGRADED & RUNNING...")
    await app.run_polling()

# ================= RUN =================
if __name__ == "__main__":
    asyncio.run(main())
