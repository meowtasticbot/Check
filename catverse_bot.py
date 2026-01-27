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

client = MongoClient(MONGO_URI)
db = client["catverse"]
cats = db["cats"]
global_state = db["global"]
leaderboard_history = db["leaderboard_history"]

# ================= LEVELS =================

LEVELS = [
    ("🐱 Kitten", 0),
    ("😺 Teen Cat", 30),
    ("😼 Rogue Cat", 60),
    ("🐯 Alpha Cat", 100),
    ("👑 Legend Cat", 160),
]

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
        "inventory": {item: 0 for item in SHOP_ITEMS},
        "dna": {"aggression": 1, "intelligence": 1, "luck": 1, "charm": 1},
        "level": "🐱 Kitten",
        "last_msg": 0,
        "protected_until": None,
        "last_daily": None,
        "last_claim": None,  # 👈 ADD THI
        "last_rob": {},
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
    total = sum(cat["dna"].values())
    for name, req in reversed(LEVELS):
        if total >= req:
            cat["level"] = name
            break

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
    await update.message.reply_text(text)

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


# 💸 GIVE MONEY
async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
# ================= SHOP SYSTEM =================

SHOP_ITEMS = {
    "fish_bait": {"price": 80, "desc": "🐟 Increases chance to find rare magic fish during chat events"},
    "bail_pass": {"price": 400, "desc": "🚔 Escape wanted penalty after failed crimes"},
    "luck_boost": {"price": 250, "desc": "🍀 Improves robbery success rate (one-time use)"},
    "shield": {"price": 350, "desc": "🛡 Blocks robberies for 1 full day"},
    "shield_breaker": {"price": 800, "desc": "💣 Destroys a target's protection during robbery"},
}


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{item.replace('_',' ').title()}", callback_data=f"shop:view:{item}")]
        for item in SHOP_ITEMS
    ]

    await update.message.reply_text(
        "🛒 *Catverse Black Market*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def shop_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cat = get_cat(query.from_user)

    # Ensure inventory exists
    if "inventory" not in cat or not isinstance(cat["inventory"], dict):
        cat["inventory"] = {}

    data = query.data

    # ================= VIEW ITEM =================
    if data.startswith("shop:view:"):
        item = data.split(":")[2]
        info = SHOP_ITEMS[item]
        owned = cat["inventory"].get(item, 0)

        text = (
            f"🧾 *{item.replace('_',' ').title()}*\n\n"
            f"{info['desc']}\n\n"
            f"💰 Price: *${info['price']}*\n"
            f"📦 Owned: *{owned}*"
        )

        keyboard = [
            [InlineKeyboardButton("🛒 Purchase", callback_data=f"shop:buy:{item}")],
            [InlineKeyboardButton("⬅ Back", callback_data="shop:back")]
        ]

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ================= BUY ITEM =================
    elif data.startswith("shop:buy:"):
        item = data.split(":")[2]
        price = SHOP_ITEMS[item]["price"]

        if cat["coins"] < price:
            return await query.answer("💸 Not enough coins!", show_alert=True)

        cat["coins"] -= price
        cat["inventory"][item] = cat["inventory"].get(item, 0) + 1

        cats.update_one({"_id": cat["_id"]}, {"$set": cat})

        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n"
            f"🧾 {item.replace('_',' ').title()} × 1\n"
            f"💰 Spent: ${price}\n"
            f"💵 Balance: ${cat['coins']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅ Back to Shop", callback_data="shop:back")]
            ])
        )

    # ================= BACK TO SHOP =================
    elif data == "shop:back":
        keyboard = [
            [InlineKeyboardButton(f"{item.replace('_',' ').title()}", callback_data=f"shop:view:{item}")]
            for item in SHOP_ITEMS
        ]

        await query.edit_message_text(
            "🛒 *Catverse Black Market*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
# ================= INVENTRY =================

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    inv = cat.get("inventory", {})

    msg = "🎒 *Your Inventory*\n\n"

    items = [f"▫️ {k.replace('_',' ').title()} × {v}" for k, v in inv.items() if v > 0]

    if items:
        msg += "\n".join(items)
    else:
        msg += "Empty 😿"

    await update.message.reply_text(msg, parse_mode="Markdown")
    
# ================= ROB =================
# ================= ROB =================
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ================= KILL =================
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # 🛡 PROTECTION CHECK (same system style as rob)
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

# ================= PROFILE =================
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Agar reply kiya ya user mention kiya
    target_user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    cat = get_cat(target_user)
    d = cat["dna"]
    rank = calculate_global_rank(cat["_id"])

    # Clickable name
    mention = f"<a href='tg://user?id={target_user.id}'>{target_user.first_name}</a>"

    await update.message.reply_text(
        f"🐾 {mention} — \n\n<b>🐾 Level:</b> {cat['level']}\n"
        f"<b>💰 Money:</b> ${cat['coins']}\n"
        f"<b>🏆 Rank:</b> #{rank}\n"
        f"<b>🐟 Fish:</b> {cat['fish']}\n"
        f"<b>⚔️ Wins:</b> {cat['kills']} | <b>💀 Deaths:</b> {cat['deaths']}\n\n"
        f"<b>DNA →</b> 😼 {d['aggression']} | 🧠 {d['intelligence']} | 🍀 {d['luck']} | 💖 {d['charm']}",
        parse_mode="HTML"
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

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("games", games))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("claim", claim))  # 👈 NEW
    app.add_handler(CommandHandler("bal", bal))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("rob", rob))
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

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fish_action))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_chat))

    print("🐱 CATVERSE FULLY UPGRADED & RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
