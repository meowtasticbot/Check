import os
import random
import time
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client["catverse"]
cats = db["cats"]
global_state = db["global"]

# ================= LEVELS =================
LEVELS = [
    ("🐱 Kitten", 0),
    ("😺 Teen Cat", 30),
    ("😼 Rogue Cat", 60),
    ("🐯 Alpha Cat", 100),
    ("👑 Legend Cat", 160),
]

# ================= SHOP ITEMS =================
SHOP_ITEMS = {
    "fish_bait": {"price": 100, "desc": "Used to attract more fish 🐟"},
    "bail_pass": {"price": 500, "desc": "Skip wanted level penalty 🛡"},
    "luck_boost": {"price": 300, "desc": "Increase your rob success chance 🍀"},
    "shield": {"price": 500, "desc": "Protect from robbers for 1 day 🛡"},
}

# ================= DATABASE =================
def get_cat(user):
    cat = cats.find_one({"_id": user.id})
    default_data = {
        "name": user.first_name,
        "coins": 1000,
        "fish": 2,
        "xp": 0,
        "kills": 0,
        "deaths": 0,
        "premium": True,
        "inventory": {item: 0 for item in SHOP_ITEMS},
        "dna": {"aggression": 1, "intelligence": 1, "luck": 1, "charm": 1},
        "level": "🐱 Kitten",
        "last_msg": 0,
        "protected_until": None,
        "last_daily": None,
        "last_rob": {},
        "wanted": 0,
        "created": datetime.now(timezone.utc),  # ✅ Fixed tzinfo
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
    total = sum(cat["dna"].values())
    for name, req in reversed(LEVELS):
        if total >= req:
            cat["level"] = name
            break

def is_protected(cat):
    return cat.get("protected_until") and cat["protected_until"] > datetime.now(timezone.utc)

def calculate_global_rank(user_id):
    all_cats = list(cats.find().sort("coins", -1))
    for idx, c in enumerate(all_cats, 1):
        if c["_id"] == user_id:
            return idx
    return 0

# ================= GAME GUIDE =================
async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    level_text = "\n".join([f"{lvl} → {req} XP" for lvl, req in LEVELS])
    text = (
        "🐱 CATVERSE GUIDE\n\n"
        "💰 /daily — Daily coins (DM only)\n"
        "💰 /bal — Check your balance\n"
        "💸 /give — Gift coins to someone (reply)\n"
        "😼 /rob — Rob a cat (reply + amount)\n"
        "⚔️ /kill — Attack a cat (reply)\n"
        "🛡 /protect — Enable 1 day protection\n"
        "🛒 /shop — Show shop items\n"
        "🛒 /buy <item> <amount> — Buy shop items\n"
        "🎒 /inventory — Check your items\n"
        "📊 /me — View your profile\n"
        "🏆 /toprich — Top richest cats\n"
        "⚔️ /topkill — Top fighters\n"
        "🎲 /fun — Random fun command\n\n"
        "🎮 Chat to gain XP & trigger fish events 🐟\n\n"
        f"📈 Levels:\n{level_text}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ================= PASSIVE XP =================
async def on_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    cat = get_cat(update.effective_user)
    now = time.time()
    if now - cat["last_msg"] < 4:
        return
    cat["last_msg"] = now
    cat["xp"] += random.randint(1, 3)
    stat = random.choice(list(cat["dna"]))
    cat["dna"][stat] += 1
    old_level = cat["level"]
    evolve(cat)
    if old_level != cat["level"]:
        await update.message.reply_text(f"✨ Your cat evolved into {cat['level']}!")
    if random.random() < 0.05:
        context.chat_data["fish_event"] = True
        await update.message.reply_text("🐟 A magic fish appeared! Type: eat | save | share")
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})

# ================= FISH EVENT =================
async def fish_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.chat_data.get("fish_event"):
        return
    cat = get_cat(update.effective_user)
    text = update.message.text.lower()
    if "eat" in text:
        cat["fish"] += 2
        cat["dna"]["aggression"] += 1
        msg = "😻 You ate the fish!"
    elif "save" in text:
        cat["dna"]["intelligence"] += 2
        msg = "🧠 Intelligence up!"
    elif "share" in text:
        cat["dna"]["charm"] += 2
        msg = "💖 Charm up!"
    else:
        return
    evolve(cat)
    context.chat_data.pop("fish_event")
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(msg)

# ================= ECONOMY =================
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return await update.message.reply_text("⚠️ Daily reward DM only.")
    cat = get_cat(update.effective_user)
    now = datetime.now(timezone.utc)
    if cat["last_daily"] and now - cat["last_daily"] < timedelta(hours=24):
        return await update.message.reply_text("⏳ Already claimed today!")
    cat["coins"] += 2000
    cat["last_daily"] = now
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text("🎁 You got 2000 coins!")

async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    await update.message.reply_text(f"💰 Coins: {cat['coins']}")

async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text("❗ Reply with /give <amount>")
    sender = get_cat(update.effective_user)
    receiver = get_cat(update.message.reply_to_message.from_user)
    amount = int(context.args[0])
    if sender["coins"] < amount:
        return await update.message.reply_text("Not enough coins.")
    tax = int(amount * 0.05)
    final = amount - tax
    sender["coins"] -= amount
    receiver["coins"] += final
    cats.update_one({"_id": sender["_id"]}, {"$set": sender})
    cats.update_one({"_id": receiver["_id"]}, {"$set": receiver})
    await update.message.reply_text(f"🐾 Sent {final} coins after tax!")

# ================= SHOP =================
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{item} — {info['price']} coins", callback_data=f"buy:{item}")]
        for item, info in SHOP_ITEMS.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛒 Shop Items (Click to Buy):", reply_markup=reply_markup)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        item = context.args[0].lower()
        amount = int(context.args[1]) if len(context.args) > 1 else 1
        cat = get_cat(update.effective_user)
        if item not in SHOP_ITEMS:
            return await update.message.reply_text("❌ Item not found!")
        cost = SHOP_ITEMS[item]["price"] * amount
        if cat["coins"] < cost:
            return await update.message.reply_text("❌ Not enough coins!")
        cat["coins"] -= cost
        cat["inventory"][item] += amount
        cats.update_one({"_id": cat["_id"]}, {"$set": cat})
        await update.message.reply_text(f"✅ Bought {amount} {item}(s) for {cost} coins!")
    else:
        await update.message.reply_text("Usage: /buy <item> <amount>")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("buy:"):
        item = query.data.split(":")[1]
        cat = get_cat(query.from_user)
        cost = SHOP_ITEMS[item]["price"]
        if cat["coins"] < cost:
            await query.edit_message_text(f"❌ Not enough coins for {item}!")
        else:
            cat["coins"] -= cost
            cat["inventory"][item] += 1
            cats.update_one({"_id": cat["_id"]}, {"$set": cat})
            await query.edit_message_text(f"✅ Bought 1 {item} for {cost} coins!")

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    inv = cat["inventory"]
    msg = "🎒 Your Inventory:\n\n"
    for item, amt in inv.items():
        msg += f"{item}: {amt}\n"
    await update.message.reply_text(msg)

# ================= ROB =================
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return await update.message.reply_text("❌ Rob works in groups only.")

    if not update.message.reply_to_message:
        return await update.message.reply_text("❗ Reply to a cat and use /rob <amount>")

    # Safe amount parsing
    try:
        amount = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("💸 Use like: /rob 400")

    if amount <= 0:
        return await update.message.reply_text("😂 Don't try to be over smart")

    thief = get_cat(update.effective_user)
    victim_user = update.message.reply_to_message.from_user

    # Can't rob yourself
    if victim_user.id == update.effective_user.id:
        return await update.message.reply_text("🙀 You can't rob yourself, silly cat!")

    # If someone tries to rob THIS bot
    if victim_user.id == context.bot.id:
        return await update.message.reply_text("😹 You tried to rob the Catverse gods… They stole YOUR milk instead!")

    # Can't rob other bots
    if victim_user.is_bot:
        return await update.message.reply_text("🤖 That’s a robot cat… no coins to steal!")

    victim = get_cat(victim_user)

    # Protection check
    if is_protected(victim) or victim["inventory"].get("shield", 0) > 0:
        return await update.message.reply_text("🛡 This cat is protected by a magic shield!")

    now = time.time()
    last = thief["last_rob"].get(str(victim["_id"]), 0)
    if now - last < 600:
        return await update.message.reply_text("⏳ You already tried robbing this cat recently!")

    fail_chance = 30 + thief.get("wanted", 0) * 5

    if thief["inventory"].get("luck_boost", 0) > 0:
        fail_chance -= 15
        thief["inventory"]["luck_boost"] -= 1

    # Rob fail
    if random.randint(1, 100) <= fail_chance:
        thief["wanted"] += 1
        cats.update_one({"_id": thief["_id"]}, {"$set": thief})
        return await update.message.reply_text(f"🚨 {update.effective_user.mention_html()} got caught trying to rob!", parse_mode="HTML")

    # Successful rob
    steal = min(amount, victim["coins"])
    if steal <= 0:
        return await update.message.reply_text("😿 That cat is broke!")

    victim["coins"] -= steal
    thief["coins"] += steal
    thief["wanted"] += 1
    thief["last_rob"][str(victim["_id"])] = now

    cats.update_one({"_id": thief["_id"]}, {"$set": thief})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    await update.message.reply_text(
        f"😼 {update.effective_user.mention_html()} successfully robbed "
        f"{victim_user.mention_html()} for 💰 {steal} coins!",
        parse_mode="HTML"
    )

# ================= KILL =================
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to attack someone.")
    attacker = get_cat(update.effective_user)
    victim = get_cat(update.message.reply_to_message.from_user)
    reward = random.randint(200, 400)
    attacker["kills"] += 1
    victim["deaths"] += 1
    attacker["coins"] += reward
    cats.update_one({"_id": attacker["_id"]}, {"$set": attacker})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})
    await update.message.reply_text(f"⚔️ Victory! +{reward} coins")

# ================= PROTECT =================
async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    if cat["coins"] < 500:
        return await update.message.reply_text("Need 500 coins for protection.")
    cat["coins"] -= 500
    cat["protected_until"] = datetime.now(timezone.utc) + timedelta(days=1)
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text("🛡 Protection enabled for 1 day.")

# ================= LEADERBOARDS =================
async def toprich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = cats.find().sort("coins", -1).limit(10)
    msg = "🏆 Top Rich Cats\n\n"
    for i, c in enumerate(top, 1):
        msg += f"{i}. {c['name']} — {c['coins']} coins\n"
    await update.message.reply_text(msg)

async def topkill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = cats.find().sort("kills", -1).limit(10)
    msg = "⚔️ Top Fighters\n\n"
    for i, c in enumerate(top, 1):
        msg += f"{i}. {c['name']} — {c['kills']} wins\n"
    await update.message.reply_text(msg)

# ================= PROFILE =================
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    d = cat["dna"]
    rank = calculate_global_rank(cat["_id"])
    await update.message.reply_text(
        f"🐾 {cat['level']}\n"
        f"💰 Coins: {cat['coins']}\n"
        f"🏆 Rank: #{rank}\n"
        f"🐟 Fish: {cat['fish']}\n"
        f"⚔️ Wins: {cat['kills']} | 💀 Deaths: {cat['deaths']}\n\n"
        f"DNA → 😼 {d['aggression']} | 🧠 {d['intelligence']} | 🍀 {d['luck']} | 💖 {d['charm']}"
    )

# ================= FUN COMMAND =================
async def fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responses = [
        "😹 You found a hidden treasure! +500 coins",
        "🐟 A fish jumps into your inventory! +1 fish",
        "💤 You took a nap, nothing happened...",
        "🍀 Lucky day! Gain +2 luck",
        "😼 Mischievous cat stole 100 coins from you (just kidding!)",
    ]
    msg = random.choice(responses)
    cat = get_cat(update.effective_user)
    if "coins" in msg:
        cat["coins"] += 500
    if "fish" in msg:
        cat["fish"] += 1
    if "luck" in msg:
        cat["dna"]["luck"] += 2
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(msg)

# ================= UPGRADE =================
UPGRADE_COSTS = {
    "aggression": 200,
    "intelligence": 200,
    "luck": 300,
    "charm": 300,
}

async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 1:
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
        return await update.message.reply_text(f"❌ Not enough coins! Upgrade costs {cost} coins.")
    cat["coins"] -= cost
    cat["dna"][stat] += amount
    evolve(cat)
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(
        f"✅ {stat.capitalize()} increased by {amount}! Spent {cost} coins.\n"
        f"New {stat.capitalize()}: {cat['dna'][stat]}\n"
        f"Current Level: {cat['level']}"
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("games", games))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("bal", bal))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("rob", rob))
    app.add_handler(CommandHandler("kill", kill))
    app.add_handler(CommandHandler("protect", protect))
    app.add_handler(CommandHandler("toprich", toprich))
    app.add_handler(CommandHandler("topkill", topkill))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CommandHandler("fun", fun))

    # Passive handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fish_action))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_chat))

    print("🐱 CATVERSE FULLY UPGRADED & RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
