import logging

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    BotCommand,
    MenuButtonCommands,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN,
    REGISTRATION_BONUS,
    REFERRAL_BONUS,
    SUPER_ADMIN_ID,
)

from database import (
    init_database,
    get_user_by_telegram_id,
    get_user_by_referral_code,
    create_user,
    add_referral_bonus,
    get_total_balance,
    get_user_profile,

    get_demo_banks,
    get_demo_bank,
    create_deposit_request,
    get_user_deposit_requests,

    create_withdrawal_request,
    get_user_withdrawal_requests,

    get_wallet_transactions,

    get_pending_deposits,
    approve_deposit,
    reject_deposit,

    get_pending_withdrawals,
    approve_withdrawal,
    reject_withdrawal,

    get_admin_statistics,
    add_demo_withdrawable_balance,
    ensure_system_setting,
    get_system_setting_float,
    set_system_setting,
    get_referral_stats,
    get_user_pending_requests,
    adjust_demo_bonus_balance,
    adjust_demo_main_balance,
    adjust_demo_withdrawable_balance,
    get_bingo_commission_percent,
    set_bingo_commission_percent,
    is_admin_user,
    has_admin_grant,
    get_admin_grants,
    get_admin_by_telegram_id,
    create_admin_user,
    set_admin_grants,
    set_admin_active,
    get_all_admins,
    ADMIN_GRANTS,
    record_admin_activity,
    get_admin_activity,
    get_admin_activity_for_admin,
    get_admin_activity_count,
    get_bingo_rooms,
    get_bingo_room,
    create_bingo_room,
    update_bingo_room,
    ensure_bingo_card_pool,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


BOT_USERNAME = None


# ============================================================
# PLAYER MENU
# ============================================================


def registered_menu(user_id=None):
    """Use Telegram's native command menu instead of a persistent reply keyboard."""
    return ReplyKeyboardRemove()


# ============================================================
# ADMIN MENU
# ============================================================


def admin_menu(user_id=None):
    keyboard = []

    if user_id is None or can_admin(user_id, "dashboard"):
        keyboard.append([KeyboardButton("📊 Admin Dashboard")])

    row = []
    if user_id is None or can_admin(user_id, "deposits"):
        row.append(KeyboardButton("💳 Pending Deposits"))
    if user_id is None or can_admin(user_id, "withdrawals"):
        row.append(KeyboardButton("💸 Pending Withdrawals"))
    if row:
        keyboard.append(row)

    row = []
    if user_id is None or can_admin(user_id, "player_balance"):
        row.append(KeyboardButton("🎁 Add Demo Winnings"))
    if row:
        keyboard.append(row)

    if user_id is None or can_admin(user_id, "player_balance"):
        keyboard.append([KeyboardButton("💰 Edit Player Balance")])

    if user_id is None or can_admin(user_id, "bingo_rooms"):
        keyboard.append([KeyboardButton("🎱 Bingo Game Settings")])

    if user_id is None or can_admin(user_id, "settings") or can_admin(user_id, "commission"):
        keyboard.append([KeyboardButton("⚙️ Admin Settings")])

    if user_id is None or is_super_admin(user_id):
        keyboard.append([KeyboardButton("👑 Manage Admins")])

    if user_id is None or can_admin(user_id, "dashboard"):
        keyboard.append([KeyboardButton("🔄 Refresh Admin")])

    keyboard.append([KeyboardButton("🚪 Exit Admin")])

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


# ============================================================
# ADMIN CHECK
# ============================================================

def is_super_admin(user_id):
    try:
        return int(user_id) == int(SUPER_ADMIN_ID)
    except Exception:
        return False


def is_admin(user_id):
    return is_super_admin(user_id) or is_admin_user(user_id)


def can_admin(user_id, grant_key):
    return is_super_admin(user_id) or has_admin_grant(user_id, grant_key)


async def log_admin_action(context, admin_id, action, details="", target_telegram_id=None):
    try:
        record_admin_activity(admin_id, action, details, target_telegram_id)
    except Exception as e:
        logger.warning("Could not record admin activity: %s", e)
    if is_super_admin(admin_id):
        return
    message = (
        "🔔 ADMIN ACTIVITY\n\n"
        f"👤 Admin Telegram ID: {admin_id}\n"
        f"📝 Action: {action}\n"
    )
    if target_telegram_id is not None:
        message += f"🎯 Target Telegram ID: {target_telegram_id}\n"
    if details:
        message += f"📌 Details: {details}"
    try:
        await context.bot.send_message(chat_id=int(SUPER_ADMIN_ID), text=message)
    except Exception as e:
        logger.warning("Super Admin activity notification failed: %s", e)


ADMIN_GRANT_LABELS = {
    "dashboard": "📊 Dashboard",
    "deposits": "💳 Deposits",
    "withdrawals": "💸 Withdrawals",
    "player_balance": "💰 Player Balance",
    "player_bonus": "🪙 Player Bonus",
    "bingo_rooms": "🎱 Bingo Game Settings",
    "bingo_settings": "🎯 Bingo Settings",
    "settings": "⚙️ General Settings",
    "commission": "💵 Game Commission",
    "manage_admins": "👑 Manage Admins",
}


ADMIN_GRANT_DESCRIPTIONS = {
    "dashboard": "View dashboard and statistics",
    "deposits": "Review and approve/reject deposits",
    "withdrawals": "Review and approve/reject withdrawals",
    "player_balance": "Adjust main/deposited and withdrawable balances",
    "player_bonus": "Adjust player bonus balances",
    "bingo_rooms": "Add/edit/disable Bingo bet games and card limits",
    "bingo_settings": "Manage Bingo game settings and patterns",
    "settings": "Edit registration/referral/withdrawal settings",
    "commission": "Edit game commission percentage",
    "manage_admins": "Create and manage other administrators",
}


# ============================================================
# WALLET CANCEL KEYBOARD
# ============================================================

def wallet_cancel_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="wallet_cancel",
            )
        ]
    ])


def wallet_cancel_reply_keyboard(*args, **kwargs):
    return ReplyKeyboardRemove()


def wallet_bank_reply_keyboard(*args, **kwargs):
    return ReplyKeyboardRemove()


def wallet_input_reply_keyboard(*args, **kwargs):
    return ReplyKeyboardRemove()


def admin_settings_menu(user_id=None):
    keyboard = []
    row = []
    if user_id is None or can_admin(user_id, "settings"):
        row.extend([
            KeyboardButton("🎁 Registration Bonus"),
            KeyboardButton("👥 Referral Bonus"),
        ])
        keyboard.append(row)
        keyboard.append([KeyboardButton("💳 First Deposit Requirement")])
        keyboard.append([KeyboardButton("💸 Withdrawal Limits")])
    if user_id is None or can_admin(user_id, "commission"):
        keyboard.append([KeyboardButton("🎯 Game Commission")])
    if user_id is None or can_admin(user_id, "player_bonus"):
        keyboard.append([KeyboardButton("🪙 Edit Player Bonus")])
    keyboard.append([KeyboardButton("↩️ Admin Menu")])
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_input_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("❌ Cancel Admin Action")],
            [KeyboardButton("↩️ Admin Menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_balance_type_menu():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("💳 Main / Deposited"),
                KeyboardButton("🏆 Withdrawable"),
            ],
            [KeyboardButton("❌ Cancel Admin Action")],
            [KeyboardButton("↩️ Admin Menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )



def bingo_admin_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📋 List Bingo Games")],
            [KeyboardButton("✏️ Edit Bingo Game")],
            [KeyboardButton("➕ Add Bet Game")],
            [KeyboardButton("🔄 Enable / Disable Game")],
            [KeyboardButton("↩️ Admin Menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_management_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Create Admin")],
            [KeyboardButton("👥 List Admins")],
            [KeyboardButton("✏️ Edit Admin Grants")],
            [KeyboardButton("🔄 Activate / Deactivate Admin")],
            [KeyboardButton("📋 Admin Activity Log")],
            [KeyboardButton("↩️ Admin Menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_grant_menu(selected=None):
    selected = set(selected or [])
    rows = []
    for grant in ADMIN_GRANTS:
        mark = "✅" if grant in selected else "⬜"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {ADMIN_GRANT_LABELS.get(grant, grant)}",
                callback_data=f"admin_grant_toggle:{grant}",
            )
        ])
    rows.append([
        InlineKeyboardButton("💾 Save Grants", callback_data="admin_grant_save"),
        InlineKeyboardButton("❌ Cancel", callback_data="admin_grant_cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def format_bingo_rooms(rooms):
    if not rooms:
        return "🎱 BINGO GAMES\n\nNo Bingo games configured."
    text = "🎱 BINGO GAMES\n\n"
    for room in rooms:
        status = "ACTIVE" if int(room["is_active"]) else "DISABLED"
        text += (
            f"🆔 ID: {room['id']}\n"
            f"💵 Bet: {room['bet_amount']}\n"
            f"🎫 Cartels: {room['max_cards']}\n"
            f"👥 Players: {room['min_players']}–{room['max_players']}\n"
            f"⏳ Countdown: {room['countdown_seconds']} sec\n"
            f"💰 Commission: {room['commission_percent']}%\n"
            f"📌 Status: {status}\n\n"
        )
    return text.rstrip()


def find_bank_from_menu_text(text):
    if not text.startswith("🏦 "):
        return None
    selected_name = text[2:].strip()
    for bank in get_demo_banks():
        if bank["bank_name"] == selected_name:
            return bank
    return None


async def show_player_pending_requests(update: Update):
    deposits, withdrawals = get_user_pending_requests(update.effective_user.id)

    if not deposits and not withdrawals:
        await update.message.reply_text(
            "⏳ PENDING REQUESTS\n\n✅ You have no pending deposit or withdrawal requests.",
            reply_markup=registered_menu(update.effective_user.id),
        )
        return

    text = "⏳ PENDING REQUESTS\n\n"
    if deposits:
        text += "💳 DEPOSITS\n"
        for item in deposits:
            text += (
                f"#{item['id']} | {item['bank_name']} | {item['amount']}\n"
                f"🧾 Transaction ID: {item['transaction_id'] or 'Not provided'}\n"
                f"📅 {item['created_at']}\n\n"
            )

    if withdrawals:
        text += "💸 WITHDRAWALS\n"
        for item in withdrawals:
            text += (
                f"#{item['id']} | {item['bank_name'] or 'Demo Bank'} | {item['amount']}\n"
                f"📅 {item['created_at']}\n\n"
            )

    await update.message.reply_text(
        text[:4000],
        reply_markup=registered_menu(update.effective_user.id),
    )


async def notify_admin_deposit(context, player, bank, request_id, amount, transaction_id):
    try:
        keyboard = [[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"admin_deposit_approve:{request_id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"admin_deposit_reject:{request_id}",
            ),
        ]]
        await context.bot.send_message(
            chat_id=int(SUPER_ADMIN_ID),
            text=(
                "🔔 NEW DEMO DEPOSIT REQUEST\n\n"
                f"🆔 Request: #{request_id}\n"
                f"👤 Player: {player.first_name or ''} {player.last_name or ''}\n"
                f"🆔 Telegram ID: {player.id}\n"
                f"🏦 Bank: {bank['bank_name']}\n"
                f"💰 Amount: {amount}\n"
                f"🧾 Transaction ID: {transaction_id}\n\n"
                "Approve or reject this request:"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.warning("Admin deposit notification failed: %s", e)


async def notify_admin_withdrawal(context, player, bank, request_id, amount, account_number, account_name):
    try:
        keyboard = [[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"admin_withdraw_approve:{request_id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"admin_withdraw_reject:{request_id}",
            ),
        ]]
        await context.bot.send_message(
            chat_id=int(SUPER_ADMIN_ID),
            text=(
                "🔔 NEW DEMO WITHDRAWAL REQUEST\n\n"
                f"🆔 Request: #{request_id}\n"
                f"👤 Player: {player.first_name or ''} {player.last_name or ''}\n"
                f"🆔 Telegram ID: {player.id}\n"
                f"🏦 Bank: {bank['bank_name'] if bank else 'Demo Bank'}\n"
                f"💰 Amount: {amount}\n"
                f"🔢 Account Number: {account_number}\n"
                f"👤 Account Name: {account_name}\n\n"
                "Approve or reject this request:"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.warning("Admin withdrawal notification failed: %s", e)



# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    user = update.effective_user

    # Every administrator, including the SUPER_ADMIN_ID, must first exist as
    # a normal registered player. Admin status only unlocks extra options;
    # it never bypasses player registration.
    existing_user = get_user_by_telegram_id(user.id)

    if existing_user:
        if is_admin(user.id):
            await update.message.reply_text(
                "👋 Welcome back!\n\n"
                "✅ Player account: registered\n"
                "🛡️ Administrator access: available\n\n"
                "Use /play for Bingo or /admin for administrator tools.",
                reply_markup=registered_menu(user.id),
            )
        else:
            await update.message.reply_text(
                "👋 Welcome back!\n\n"
                "You are already registered with us.\n\n"
                "Use /play to open Bingo.",
                reply_markup=registered_menu(user.id),
            )
        return


    referral_code = None

    if context.args:

        referral_code = context.args[0].strip()

        referrer = get_user_by_referral_code(
            referral_code
        )

        if referrer:

            if int(referrer["telegram_user_id"]) == int(
                user.id
            ):
                referral_code = None

            else:
                context.user_data[
                    "referral_code"
                ] = referral_code

        else:
            referral_code = None


    phone_button = KeyboardButton(
        "📱 Share Phone Number",
        request_contact=True,
    )

    keyboard = ReplyKeyboardMarkup(
        [[phone_button]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


    await update.message.reply_text(
        "🎉 Welcome to Bingo Game!\n\n"
        "To create your account, please share "
        "your Telegram phone number.\n\n"
        "🔐 Your phone number is used for account "
        "registration.",
        reply_markup=keyboard,
    )


# ============================================================
# REGISTRATION
# ============================================================


async def contact_received(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.contact:
        return

    user = update.effective_user
    contact = update.message.contact
    if not user:
        return

    if contact.user_id != user.id:
        await update.message.reply_text(
            "❌ Please use the button to share your own Telegram phone number."
        )
        return

    existing_user = get_user_by_telegram_id(user.id)
    if existing_user:
        await update.message.reply_text(
            "⚠️ You are already registered.",
            reply_markup=registered_menu(user.id),
        )
        return

    referral_code = context.user_data.get("referral_code")
    registration_bonus = get_system_setting_float("registration_bonus", REGISTRATION_BONUS)
    referral_bonus = get_system_setting_float("referral_bonus", REFERRAL_BONUS)

    try:
        new_user, status = create_user(
            telegram_user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=contact.phone_number,
            registration_bonus=registration_bonus,
            referral_code=referral_code,
        )
    except Exception as e:
        logger.exception("Registration error: %s", e)
        await update.message.reply_text("❌ Registration failed.\n\nPlease try again.")
        return

    if status == "already_registered":
        await update.message.reply_text(
            "⚠️ You are already registered.",
            reply_markup=registered_menu(user.id),
        )
        return

    if status == "phone_exists":
        await update.message.reply_text(
            "⚠️ This phone number is already registered to another account."
        )
        return

    if status != "created":
        await update.message.reply_text("❌ Registration failed.\n\nPlease try again.")
        return

    total_balance = get_total_balance(user.id)
    await update.message.reply_text(
        "✅ Registration Successful!\n\n"
        f"🎁 Registration bonus: {registration_bonus}\n"
        f"💰 Demo balance: {total_balance}\n\n"
        "Your account is ready.",
        reply_markup=registered_menu(user.id),
    )

    if referral_code:
        referrer = get_user_by_referral_code(referral_code)
        if referrer:
            try:
                result = add_referral_bonus(
                    int(referrer["id"]),
                    int(new_user["id"]),
                    referral_bonus,
                )
                if result:
                    referrer_id = int(referrer["telegram_user_id"])
                    balance_now = get_total_balance(referrer_id)
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=(
                            "🎉 Referral Bonus Received!\n\n"
                            "👤 A new player registered using your referral link.\n\n"
                            f"🎁 Referral bonus: {referral_bonus}\n"
                            f"💰 Your new total balance: {balance_now}\n\n"
                            "Keep inviting friends! 👥"
                        ),
                        reply_markup=registered_menu(referrer_id),
                    )
            except Exception as e:
                logger.exception("Referral error: %s", e)

    context.user_data.pop("referral_code", None)



# ============================================================
# BALANCE
# ============================================================

async def balance(update: Update):

    user = update.effective_user

    if not user:
        return


    account = get_user_by_telegram_id(
        user.id
    )


    if not account:

        await update.message.reply_text(
            "❌ You are not registered.\n\n"
            "Use /start."
        )

        return


    total = get_total_balance(account)


    await update.message.reply_text(
        "💰 YOUR BALANCE\n\n"
        f"💵 Total Balance: {total}\n\n"
        f"💳 Main / Deposited: "
        f"{account['main_balance']}\n"
        f"🎁 Bonus: "
        f"{account['bonus_balance']}\n"
        f"🏆 Withdrawable: "
        f"{account['withdrawable_balance']}\n\n"
        "All balances are demo balances."
    )


# ============================================================
# PROFILE
# ============================================================

async def profile(update: Update):

    user = update.effective_user

    if not user:
        return


    account = get_user_profile(
        user.id
    )


    if not account:

        await update.message.reply_text(
            "❌ Profile not found.\n\n"
            "Use /start."
        )

        return


    username = account["username"]

    if username:
        username = "@" + username
    else:
        username = "Not set"


    full_name = (
        f"{account['first_name'] or ''} "
        f"{account['last_name'] or ''}"
    ).strip()


    if not full_name:
        full_name = "Not set"


    await update.message.reply_text(
        "👤 YOUR PROFILE\n\n"
        f"🆔 Telegram ID: "
        f"{account['telegram_user_id']}\n"
        f"👤 Username: {username}\n"
        f"📛 Name: {full_name}\n"
        f"📱 Phone: "
        f"{account['phone_number'] or 'Not set'}\n\n"
        f"💰 Main Balance: "
        f"{account['main_balance']}\n"
        f"🎁 Bonus Balance: "
        f"{account['bonus_balance']}\n"
        f"🏆 Withdrawable: "
        f"{account['withdrawable_balance']}\n\n"
        f"💳 Total Deposited: "
        f"{account['total_deposited']}\n"
        f"💸 Total Withdrawn: "
        f"{account['total_withdrawn']}\n"
        f"🏆 Total Won: "
        f"{account['total_won']}\n\n"
        f"📅 Registered: "
        f"{account['registered_at']}"
    )


# ============================================================
# GAMES
# ============================================================

async def games(update: Update):
    user = update.effective_user
    if not user or not get_user_by_telegram_id(user.id):
        await update.message.reply_text(
            "📱 Please register first with /start before opening the games."
        )
        return

    keyboard = [[
        InlineKeyboardButton(
            "🎱 Bingo",
            web_app=WebAppInfo(url=MINI_APP_URL),
        )
    ]]
    await update.message.reply_text(
        "🎮 GAMES\n\nTap a game below to open it.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# DEPOSIT START
# ============================================================


async def start_deposit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    banks = get_demo_banks()

    if not banks:
        await update.message.reply_text(
            "❌ No demo banks are available.",
            reply_markup=registered_menu(update.effective_user.id),
        )
        return

    context.user_data["wallet_action"] = "DEPOSIT_BANK"
    for key in ("deposit_bank_id", "deposit_amount", "deposit_transaction_id"):
        context.user_data.pop(key, None)

    keyboard = []
    for bank in banks:
        keyboard.append([
            InlineKeyboardButton(
                f"{bank['bank_name']} - {bank['account_number']}",
                callback_data=f"deposit_bank:{bank['id']}",
            )
        ])
    keyboard.append([
        InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")
    ])

    await update.message.reply_text(
        "💳 DEMO DEPOSIT\n\n"
        "Choose the demo bank where you want to make your deposit.\n\n"
        "The same bank can only have one pending deposit request at a time, "
        "but you may create another pending request using a different bank.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    await update.message.reply_text(
        "🏦 The same bank choices are also available in your Telegram menu.",
        reply_markup=wallet_bank_reply_keyboard(banks),
    )



# ============================================================
# DEPOSIT BANK CALLBACK
# ============================================================


async def deposit_bank_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    try:
        bank_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Invalid bank selection.")
        return

    bank = get_demo_bank(bank_id)
    if not bank:
        await query.edit_message_text("❌ The selected demo bank is no longer available.")
        return

    context.user_data["deposit_bank_id"] = bank_id
    context.user_data["wallet_action"] = "DEPOSIT_AMOUNT"

    await query.edit_message_text(
        "💳 DEMO BANK SELECTED\n\n"
        f"🏦 Bank: {bank['bank_name']}\n"
        f"🔢 Demo Account: {bank['account_number']}\n\n"
        "Now enter the deposit amount.",
        reply_markup=wallet_cancel_keyboard(),
    )

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="💰 Enter the demo deposit amount in the chat field.",
        reply_markup=wallet_input_reply_keyboard(),
    )



# ============================================================
# WITHDRAW START
# ============================================================


async def start_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = get_user_by_telegram_id(update.effective_user.id)

    if not user:
        await update.message.reply_text(
            "❌ Account not found.",
            reply_markup=registered_menu(update.effective_user.id),
        )
        return

    withdrawable = float(user["withdrawable_balance"])
    first_required = get_system_setting_float("first_deposit_required", 200)
    min_withdrawal = get_system_setting_float("min_withdrawal", 100)
    max_withdrawal = get_system_setting_float("max_withdrawal", 10000)

    if withdrawable <= 0:
        await update.message.reply_text(
            "💸 WITHDRAW\n\n"
            "You currently have no withdrawable balance.\n\n"
            "Only game winnings can be withdrawn.",
            reply_markup=registered_menu(update.effective_user.id),
        )
        return

    if (
        float(user["total_withdrawn"] or 0) <= 0
        and float(user["total_deposited"] or 0) < first_required
    ):
        still_needed = max(0, first_required - float(user["total_deposited"] or 0))
        await update.message.reply_text(
            "💸 FIRST WITHDRAWAL REQUIREMENT\n\n"
            f"Before your first withdrawal, you must have at least {first_required} "
            "in approved demo deposits.\n\n"
            f"✅ Approved deposits so far: {float(user['total_deposited'] or 0)}\n"
            f"📌 Still required: {still_needed}\n\n"
            "After your first approved withdrawal, this first-deposit check is no longer needed.",
            reply_markup=registered_menu(update.effective_user.id),
        )
        return

    banks = get_demo_banks()
    if not banks:
        await update.message.reply_text(
            "❌ No demo banks are available.",
            reply_markup=registered_menu(update.effective_user.id),
        )
        return

    context.user_data["wallet_action"] = "WITHDRAW_BANK"
    for key in (
        "withdraw_bank_id",
        "withdraw_amount",
        "withdraw_account_number",
        "withdraw_account_name",
    ):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        "💸 DEMO WITHDRAWAL\n\n"
        f"🏆 Available: {withdrawable}\n"
        f"⬇️ Minimum: {min_withdrawal}\n"
        f"⬆️ Maximum: {max_withdrawal}\n\n"
        "First choose the demo bank where you want to receive the withdrawal:",
        reply_markup=wallet_bank_reply_keyboard(banks),
    )

    keyboard = []
    for bank in banks:
        keyboard.append([
            InlineKeyboardButton(
                f"{bank['bank_name']} - {bank['account_number']}",
                callback_data=f"withdraw_bank:{bank['id']}",
            )
        ])
    keyboard.append([
        InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")
    ])

    await update.message.reply_text(
        "🏦 Choose Demo Bank",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



# ============================================================
# WITHDRAW BANK CALLBACK
# ============================================================


async def withdraw_bank_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    try:
        bank_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Invalid bank selection.")
        return

    bank = get_demo_bank(bank_id)
    if not bank:
        await query.edit_message_text("❌ The selected demo bank is no longer available.")
        return

    context.user_data["withdraw_bank_id"] = bank_id
    context.user_data["wallet_action"] = "WITHDRAW_ACCOUNT_NUMBER"

    await query.edit_message_text(
        "🏦 DEMO BANK SELECTED\n\n"
        f"🏦 Bank: {bank['bank_name']}\n\n"
        "Now enter the demo account number.",
        reply_markup=wallet_cancel_keyboard(),
    )

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="🔢 Enter the demo account number in the chat field.",
        reply_markup=wallet_input_reply_keyboard(),
    )



# ============================================================
# TRANSACTIONS
# ============================================================

async def transactions(update: Update):

    user = update.effective_user

    records = get_wallet_transactions(
        user.id
    )


    if not records:

        await update.message.reply_text(
            "📜 TRANSACTIONS\n\n"
            "No transactions yet."
        )

        return


    text = "📜 TRANSACTIONS\n\n"


    for item in records:

        text += (
            f"#{item['id']} "
            f"{item['transaction_type']}\n"
            f"Amount: {item['amount']}\n"
            f"Balance: {item['balance_after']}\n"
            f"{item['description'] or ''}\n"
            f"{item['created_at']}\n\n"
        )


    await update.message.reply_text(
        text[:4000]
    )


# ============================================================
# INVITE
# ============================================================


async def invite(update: Update):
    user = update.effective_user
    account = get_user_by_telegram_id(user.id)

    if not account:
        await update.message.reply_text("❌ Please register first.")
        return

    referral_code = account["referral_code"]
    referral_bonus = get_system_setting_float("referral_bonus", REFERRAL_BONUS)
    stats = get_referral_stats(user.id)

    if BOT_USERNAME:
        link = f"https://t.me/{BOT_USERNAME}?start={referral_code}"
    else:
        link = f"Referral code: {referral_code}"

    await update.message.reply_text(
        "👥 INVITE FRIENDS\n\n"
        f"🎁 Referral bonus per invited player: {referral_bonus}\n"
        f"👤 Total players invited: {stats['count']}\n"
        f"🎁 Total referral bonus earned: {stats['total_bonus']}\n\n"
        f"🔗 Your referral link:\n{link}",
        reply_markup=registered_menu(user.id),
    )



# ============================================================
# SUPPORT
# ============================================================

async def support(update: Update):

    await update.message.reply_text(
        "🆘 SUPPORT\n\n"
        "Demo support system.\n\n"
        "📞 Phone: Demo Support\n"
        "💬 Telegram: Demo Support Chat\n"
        "📧 Email: support@example.com"
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================


async def admin_dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    if not can_admin(user.id, "dashboard"):
        await update.message.reply_text("⛔ Access denied.")
        return

    stats = get_admin_statistics()
    registration_bonus = get_system_setting_float("registration_bonus", REGISTRATION_BONUS)
    referral_bonus = get_system_setting_float("referral_bonus", REFERRAL_BONUS)
    first_required = get_system_setting_float("first_deposit_required", 200)
    min_withdrawal = get_system_setting_float("min_withdrawal", 100)
    max_withdrawal = get_system_setting_float("max_withdrawal", 10000)

    text = (
        "📊 ADMIN DASHBOARD\n\n"
        "📊 PLATFORM STATISTICS\n\n"
        f"👥 Registered Players: {stats['users']}\n"
        f"💳 Total Approved Deposited: {stats['deposited']}\n"
        f"💸 Total Approved Withdrawn: {stats['withdrawn']}\n"
        f"🏆 Withdrawable Player Balance: {stats['withdrawable']}\n\n"
        "📥 REQUEST TOTALS\n\n"
        f"💳 Total Deposit Requested: {stats['total_deposit_requested']}\n"
        f"💸 Total Withdrawal Requested: {stats['total_withdrawal_requested']}\n"
        f"⏳ Pending Deposit Amount: {stats['pending_deposit_amount']}\n"
        f"⏳ Pending Withdrawal Amount: {stats['pending_withdrawal_amount']}\n"
        f"💳 Pending Deposit Requests: {stats['pending_deposits']}\n"
        f"💸 Pending Withdrawal Requests: {stats['pending_withdrawals']}\n\n"
        "⚙️ CURRENT SETTINGS\n\n"
        f"🎁 Registration Bonus: {registration_bonus}\n"
        f"👥 Referral Bonus: {referral_bonus}\n"
        f"💳 First Withdrawal Deposit Requirement: {first_required}\n"
        f"⬇️ Minimum Withdrawal: {min_withdrawal}\n"
        f"⬆️ Maximum Withdrawal: {max_withdrawal}"
    )

    await update.message.reply_text(text, reply_markup=admin_menu(user.id))



# ============================================================
# ADMIN PENDING DEPOSITS
# ============================================================


async def admin_pending_deposits(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    if not can_admin(user.id, "deposits"):
        await update.message.reply_text("⛔ Access denied.")
        return

    deposits = get_pending_deposits()
    if not deposits:
        await update.message.reply_text(
            "💳 PENDING DEPOSITS\n\n✅ No pending deposits.",
            reply_markup=admin_menu(user.id),
        )
        return

    for deposit in deposits:
        name = f"{deposit['first_name'] or ''} {deposit['last_name'] or ''}".strip() or "Unknown"
        username = "@" + deposit["username"] if deposit["username"] else "No username"
        text = (
            "💳 PENDING DEPOSIT\n\n"
            f"🆔 Request: #{deposit['id']}\n"
            f"👤 Player: {name}\n"
            f"📱 Username: {username}\n"
            f"🆔 Telegram ID: {deposit['telegram_user_id']}\n\n"
            f"💰 Amount: {deposit['amount']}\n"
            f"🧾 Transaction ID: {deposit['transaction_id'] or 'Not provided'}\n\n"
            f"🏦 Bank: {deposit['bank_name']}\n"
            f"👤 Account: {deposit['account_name']}\n"
            f"🔢 Number: {deposit['account_number']}\n\n"
            f"📅 Created: {deposit['created_at']}"
        )
        keyboard = [[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"admin_deposit_approve:{deposit['id']}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"admin_deposit_reject:{deposit['id']}",
            ),
        ]]
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    await update.message.reply_text(
        "Admin menu is ready.",
        reply_markup=admin_menu(user.id),
    )



# ============================================================
# ADMIN PENDING WITHDRAWALS
# ============================================================


async def admin_pending_withdrawals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    if not can_admin(user.id, "withdrawals"):
        await update.message.reply_text("⛔ Access denied.")
        return

    withdrawals = get_pending_withdrawals()
    if not withdrawals:
        await update.message.reply_text(
            "💸 PENDING WITHDRAWALS\n\n✅ No pending withdrawals.",
            reply_markup=admin_menu(user.id),
        )
        return

    for withdrawal in withdrawals:
        name = f"{withdrawal['first_name'] or ''} {withdrawal['last_name'] or ''}".strip() or "Unknown"
        username = "@" + withdrawal["username"] if withdrawal["username"] else "No username"
        text = (
            "💸 PENDING WITHDRAWAL\n\n"
            f"🆔 Request: #{withdrawal['id']}\n"
            f"👤 Player: {name}\n"
            f"📱 Username: {username}\n"
            f"🆔 Telegram ID: {withdrawal['telegram_user_id']}\n\n"
            f"💰 Amount: {withdrawal['amount']}\n\n"
            f"🏦 Bank: {withdrawal['bank_name'] or 'Legacy / Not recorded'}\n"
            f"🏦 Account Number: {withdrawal['account_number']}\n"
            f"👤 Account Name: {withdrawal['account_name']}\n\n"
            f"📅 Created: {withdrawal['created_at']}"
        )
        keyboard = [[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"admin_withdraw_approve:{withdrawal['id']}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"admin_withdraw_reject:{withdrawal['id']}",
            ),
        ]]
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    await update.message.reply_text(
        "Admin menu is ready.",
        reply_markup=admin_menu(user.id),
    )



# ============================================================
# ADMIN DEPOSIT APPROVAL CALLBACK
# ============================================================

async def admin_deposit_approve_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    user = query.from_user


    if not can_admin(user.id, "deposits"):

        await query.answer(
            "Access denied.",
            show_alert=True,
        )

        return


    await query.answer("Deposit approved successfully.")


    request_id = int(
        query.data.split(":")[1]
    )


    try:

        player, status, approved_amount = approve_deposit(
            request_id
        )


        if status != "approved":

            await query.edit_message_text(
                "⚠️ This deposit has already "
                "been processed."
            )

            return


        await log_admin_action(context, user.id, "APPROVE DEPOSIT", f"Request=#{request_id}; Amount={approved_amount}", player["telegram_user_id"])

        amount = player[
            "main_balance"
        ]


        total = get_total_balance(
            player
        )


        await query.edit_message_text(
            "✅ DEPOSIT APPROVED SUCCESSFULLY\n\n"
            f"Request: #{request_id}\n"
            f"Player: "
            f"{player['telegram_user_id']}\n"
            f"New main balance: {amount}\n"
            f"Total balance: {total}"
        )


        try:

            await context.bot.send_message(
                chat_id=int(
                    player["telegram_user_id"]
                ),
                text=(
                    "✅ Deposit Approved Successfully!\n\n"
                    f"💳 Your demo deposit of "
                    f"{approved_amount} "
                    f"has been approved successfully.\n\n"
                    "💰 Your deposited balance has "
                    "been updated.\n\n"
                    "Thank you."
                ),
                reply_markup=registered_menu(player["telegram_user_id"]),
            )

        except Exception as e:

            logger.warning(
                "Player notification failed: %s",
                e,
            )


    except Exception as e:

        logger.exception(
            "Deposit approval error: %s",
            e,
        )

        await query.edit_message_text(
            "❌ Deposit approval failed."
        )


# ============================================================
# ADMIN DEPOSIT REJECT CALLBACK
# ============================================================

async def admin_deposit_reject_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    user = query.from_user


    if not can_admin(user.id, "deposits"):

        await query.answer(
            "Access denied.",
            show_alert=True,
        )

        return


    await query.answer()


    request_id = int(
        query.data.split(":")[1]
    )


    try:

        player, status = reject_deposit(
            request_id
        )


        if status != "rejected":

            await query.edit_message_text(
                "⚠️ This deposit has already "
                "been processed."
            )

            return


        await log_admin_action(context, user.id, "REJECT DEPOSIT", f"Request=#{request_id}", player["telegram_user_id"])

        await query.edit_message_text(
            "❌ DEPOSIT REJECTED\n\n"
            f"Request: #{request_id}\n"
            f"Player: "
            f"{player['telegram_user_id']}"
        )


        try:

            await context.bot.send_message(
                chat_id=int(
                    player["telegram_user_id"]
                ),
                text=(
                    "❌ Deposit Rejected\n\n"
                    f"Your deposit request "
                    f"#{request_id} was rejected "
                    "by the Super Admin.\n\n"
                    "No balance was added."
                ),
                reply_markup=registered_menu(player["telegram_user_id"]),
            )

        except Exception as e:

            logger.warning(
                "Player notification failed: %s",
                e,
            )


    except Exception as e:

        logger.exception(
            "Deposit rejection error: %s",
            e,
        )

        await query.edit_message_text(
            "❌ Deposit rejection failed."
        )


# ============================================================
# ADMIN WITHDRAW APPROVAL
# ============================================================

async def admin_withdraw_approve_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    user = query.from_user


    if not can_admin(user.id, "withdrawals"):

        await query.answer(
            "Access denied.",
            show_alert=True,
        )

        return


    await query.answer()


    request_id = int(
        query.data.split(":")[1]
    )


    try:

        player, status, approved_amount = approve_withdrawal(
            request_id
        )


        if status != "approved":

            await query.edit_message_text(
                "⚠️ This withdrawal has already "
                "been processed."
            )

            return


        await log_admin_action(context, user.id, "APPROVE WITHDRAWAL", f"Request=#{request_id}; Amount={approved_amount}", player["telegram_user_id"])

        await query.edit_message_text(
            "✅ WITHDRAWAL APPROVED SUCCESSFULLY\n\n"
            f"Request: #{request_id}\n"
            f"Player: "
            f"{player['telegram_user_id']}\n"
            f"Amount: {approved_amount}"
        )


        try:

            await context.bot.send_message(
                chat_id=int(
                    player["telegram_user_id"]
                ),
                text=(
                    "✅ Withdrawal Approved Successfully!\n\n"
                    f"Your withdrawal request "
                    f"#{request_id} for {approved_amount} "
                    "has been approved "
                    "by the Super Admin.\n\n"
                    "The reserved amount remains "
                    "deducted from your withdrawable "
                    "balance."
                ),
                reply_markup=registered_menu(player["telegram_user_id"]),
            )

        except Exception as e:

            logger.warning(
                "Player notification failed: %s",
                e,
            )


    except Exception as e:

        logger.exception(
            "Withdrawal approval error: %s",
            e,
        )

        await query.edit_message_text(
            "❌ Withdrawal approval failed."
        )


# ============================================================
# ADMIN WITHDRAW REJECTION
# ============================================================

async def admin_withdraw_reject_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    user = query.from_user


    if not can_admin(user.id, "withdrawals"):

        await query.answer(
            "Access denied.",
            show_alert=True,
        )

        return


    await query.answer()


    request_id = int(
        query.data.split(":")[1]
    )


    try:

        player, status = reject_withdrawal(
            request_id
        )


        if status != "rejected":

            await query.edit_message_text(
                "⚠️ This withdrawal has already "
                "been processed."
            )

            return


        await log_admin_action(context, user.id, "REJECT WITHDRAWAL", f"Request=#{request_id}", player["telegram_user_id"])

        await query.edit_message_text(
            "❌ WITHDRAWAL REJECTED\n\n"
            f"Request: #{request_id}\n"
            f"Player: "
            f"{player['telegram_user_id']}\n\n"
            "The reserved amount was returned."
        )


        try:

            await context.bot.send_message(
                chat_id=int(
                    player["telegram_user_id"]
                ),
                text=(
                    "❌ Withdrawal Rejected\n\n"
                    f"Your withdrawal request "
                    f"#{request_id} was rejected.\n\n"
                    "💰 The reserved amount has "
                    "been returned to your "
                    "withdrawable balance."
                ),
                reply_markup=registered_menu(player["telegram_user_id"]),
            )

        except Exception as e:

            logger.warning(
                "Player notification failed: %s",
                e,
            )


    except Exception as e:

        logger.exception(
            "Withdrawal rejection error: %s",
            e,
        )

        await query.edit_message_text(
            "❌ Withdrawal rejection failed."
        )


# ============================================================
# CANCEL
# ============================================================


async def wallet_cancel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    for key in (
        "wallet_action",
        "deposit_bank_id",
        "deposit_amount",
        "deposit_transaction_id",
        "withdraw_bank_id",
        "withdraw_amount",
        "withdraw_account_number",
        "withdraw_account_name",
    ):
        context.user_data.pop(key, None)

    await query.edit_message_text("❌ Cancelled.")
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="Choose an option from the menu below.",
        reply_markup=registered_menu(update.effective_user.id),
    )



# ============================================================
# ADMIN GRANT CALLBACKS
# ============================================================

async def admin_grant_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_super_admin(user.id):
        await query.answer("Super Admin only.", show_alert=True)
        return

    data = query.data
    selected = set(context.user_data.get("grant_selection", set()))

    if data.startswith("admin_grant_toggle:"):
        grant = data.split(":", 1)[1]
        if grant in selected:
            selected.remove(grant)
        elif grant in ADMIN_GRANTS:
            selected.add(grant)
        context.user_data["grant_selection"] = selected
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=admin_grant_menu(selected))
        return

    if data == "admin_grant_save":
        target_id = context.user_data.get("grant_target_id")
        mode = context.user_data.get("grant_mode")
        if not target_id or mode not in ("CREATE", "EDIT"):
            await query.answer("Grant session expired.", show_alert=True)
            return
        try:
            if mode == "CREATE":
                admin, status = create_admin_user(target_id, selected, created_by=user.id)
                if status != "created":
                    await query.answer("Could not create administrator.", show_alert=True)
                    return
                message = "✅ ADMIN CREATED SUCCESSFULLY"
            else:
                admin, status = set_admin_grants(target_id, selected)
                if status != "updated":
                    await query.answer("Could not update grants.", show_alert=True)
                    return
                message = "✅ ADMIN GRANTS UPDATED"
            await log_admin_action(
                context, user.id,
                "CREATE ADMIN" if mode == "CREATE" else "EDIT ADMIN GRANTS",
                f"Grants: {', '.join(sorted(selected)) or 'none'}", target_id,
            )
            context.user_data.pop("grant_target_id", None)
            context.user_data.pop("grant_mode", None)
            context.user_data.pop("grant_selection", None)
            await query.answer("Saved successfully.")
            await query.edit_message_text(
                f"{message}\n\n"
                f"🆔 Telegram ID: {target_id}\n"
                f"🔐 Grants: {', '.join(ADMIN_GRANT_LABELS.get(g, g) for g in sorted(selected)) or 'No grants'}"
            )
            await context.bot.send_message(
                chat_id=user.id,
                text="Choose another admin-management option.",
                reply_markup=admin_management_menu(),
            )
        except Exception as e:
            logger.exception("Admin grant save error: %s", e)
            await query.answer("Could not save grants.", show_alert=True)
        return

    if data == "admin_grant_cancel":
        context.user_data.pop("grant_target_id", None)
        context.user_data.pop("grant_mode", None)
        context.user_data.pop("grant_selection", None)
        await query.answer("Cancelled.")
        await query.edit_message_text("❌ Admin grant editing cancelled.")
        await context.bot.send_message(chat_id=user.id, text="Admin management menu.", reply_markup=admin_management_menu())
        return


# ============================================================
# ADMIN DETAIL / PERSONAL ACTIVITY VIEW
# ============================================================

def admin_detail_keyboard(telegram_user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Refresh Activity", callback_data=f"admin_detail:{telegram_user_id}")],
        [InlineKeyboardButton("↩️ Admin List", callback_data="admin_list")],
    ])


def format_admin_detail(admin, activities):
    status = "🟢 ACTIVE" if int(admin["is_active"]) else "🔴 DISABLED"
    grants = ", ".join(ADMIN_GRANT_LABELS.get(g, g) for g in admin["grants"]) or "No grants"
    body = (
        "👤 ADMIN DETAILS\n\n"
        f"🆔 Telegram ID: {admin['telegram_user_id']}\n"
        f"📌 Status: {status}\n"
        f"👑 Created by: {admin['created_by'] or 'System / Super Admin'}\n"
        f"📅 Created: {admin['created_at']}\n"
        f"🔐 Grants: {grants}\n"
        f"📊 Total recorded actions: {get_admin_activity_count(admin['telegram_user_id'])}\n\n"
        "📝 THIS ADMIN'S OWN ACTIVITY LOG\n"
    )
    if not activities:
        return body + "\nNo activity has been recorded for this administrator yet."
    for item in activities:
        body += f"\n#{item['id']} | {item['created_at']}\n📝 {item['action']}\n"
        if item["target_telegram_id"] is not None:
            body += f"🎯 Target: {item['target_telegram_id']}\n"
        if item["details"]:
            body += f"📌 {item['details']}\n"
    return body


async def admin_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_super_admin(user.id):
        await query.answer("Super Admin only.", show_alert=True)
        return
    telegram_user_id = int(query.data.split(":", 1)[1])
    admin = get_admin_by_telegram_id(telegram_user_id)
    if not admin:
        await query.answer("Administrator not found.", show_alert=True)
        return
    admin_dict = next((a for a in get_all_admins() if int(a["telegram_user_id"]) == telegram_user_id), None)
    if not admin_dict:
        await query.answer("Administrator not found.", show_alert=True)
        return
    activities = get_admin_activity_for_admin(telegram_user_id, 100)
    await query.answer()
    await query.edit_message_text(format_admin_detail(admin_dict, activities), reply_markup=admin_detail_keyboard(telegram_user_id))


async def admin_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_super_admin(user.id):
        await query.answer("Super Admin only.", show_alert=True)
        return
    buttons = []
    for admin in get_all_admins():
        status = "🟢" if int(admin["is_active"]) else "🔴"
        buttons.append([InlineKeyboardButton(f"{status} Admin {admin['telegram_user_id']}", callback_data=f"admin_detail:{admin['telegram_user_id']}")])
    if not buttons:
        buttons.append([InlineKeyboardButton("No administrators", callback_data="admin_list")])
    await query.answer()
    await query.edit_message_text("👥 ADMIN LIST\n\nSelect an administrator to view full details and his own activity log.", reply_markup=InlineKeyboardMarkup(buttons))


# ============================================================
# TEXT HANDLER
# ============================================================


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    text = update.message.text.strip()
    user = update.effective_user

    # --------------------------------------------------------
    # ACTIVE WALLET PROCESS: CANCEL
    # --------------------------------------------------------
    if text == "❌ Cancel" and context.user_data.get("wallet_action"):
        for key in (
            "wallet_action",
            "deposit_bank_id",
            "deposit_amount",
            "deposit_transaction_id",
            "withdraw_bank_id",
            "withdraw_amount",
            "withdraw_account_number",
            "withdraw_account_name",
        ):
            context.user_data.pop(key, None)

        await update.message.reply_text(
            "❌ Process cancelled.\n\nChoose an option from the menu below.",
            reply_markup=registered_menu(user.id),
        )
        return

    wallet_action = context.user_data.get("wallet_action")

    # --------------------------------------------------------
    # DEPOSIT BANK SELECTED FROM TELEGRAM REPLY MENU
    # --------------------------------------------------------
    if wallet_action == "DEPOSIT_BANK":
        bank = find_bank_from_menu_text(text)
        if not bank:
            await update.message.reply_text(
                "🏦 Please choose one of the demo banks from the menu, or tap Cancel.",
                reply_markup=wallet_bank_reply_keyboard(get_demo_banks()),
            )
            return

        context.user_data["deposit_bank_id"] = bank["id"]
        context.user_data["wallet_action"] = "DEPOSIT_AMOUNT"
        await update.message.reply_text(
            "💳 DEMO BANK SELECTED\n\n"
            f"🏦 Bank: {bank['bank_name']}\n"
            f"🔢 Demo Account: {bank['account_number']}\n\n"
            "Now enter the deposit amount.",
            reply_markup=wallet_input_reply_keyboard(),
        )
        return

    # --------------------------------------------------------
    # WITHDRAW BANK SELECTED FROM TELEGRAM REPLY MENU
    # --------------------------------------------------------
    if wallet_action == "WITHDRAW_BANK":
        bank = find_bank_from_menu_text(text)
        if not bank:
            await update.message.reply_text(
                "🏦 Please choose one of the demo banks from the menu, or tap Cancel.",
                reply_markup=wallet_bank_reply_keyboard(get_demo_banks()),
            )
            return

        context.user_data["withdraw_bank_id"] = bank["id"]
        context.user_data["wallet_action"] = "WITHDRAW_ACCOUNT_NUMBER"
        await update.message.reply_text(
            "🏦 DEMO BANK SELECTED\n\n"
            f"🏦 Bank: {bank['bank_name']}\n\n"
            "Now enter the demo account number.",
            reply_markup=wallet_input_reply_keyboard(),
        )
        return

    # --------------------------------------------------------
    # ADMIN INPUT ACTIONS
    # --------------------------------------------------------
    if is_admin(user.id):
        admin_action = context.user_data.get("admin_action")

        action_grants = {
            "DEMO_USER_ID": "player_balance",
            "DEMO_AMOUNT": "player_balance",
            "BONUS_USER_ID": "player_bonus",
            "BONUS_AMOUNT": "player_bonus",
            "BALANCE_USER_ID": "player_balance",
            "BALANCE_TYPE": "player_balance",
            "BALANCE_AMOUNT": "player_balance",
            "SET_REGISTRATION_BONUS": "settings",
            "SET_REFERRAL_BONUS": "settings",
            "SET_FIRST_DEPOSIT_REQUIRED": "settings",
            "SET_WITHDRAWAL_LIMITS": "settings",
            "SET_BINGO_COMMISSION": "commission",
            "ADD_BINGO_ROOM": "bingo_rooms",
            "EDIT_BINGO_ROOM_ID": "bingo_rooms",
            "EDIT_BINGO_ROOM_VALUES": "bingo_rooms",
            "TOGGLE_BINGO_ROOM_ID": "bingo_rooms",
        }
        required_grant = action_grants.get(admin_action)
        if required_grant and not can_admin(user.id, required_grant):
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                "⛔ You do not have permission for that action.",
                reply_markup=admin_menu(user.id),
            )
            return

        if text in ("❌ Cancel Admin Action", "↩️ Admin Menu"):
            for key in (
                "admin_action",
                "demo_winnings_user_id",
                "bonus_user_id",
                "balance_user_id",
                "balance_type",
            ):
                context.user_data.pop(key, None)
            await update.message.reply_text(
                "👑 Admin menu.",
                reply_markup=admin_menu(user.id),
            )
            return

        if admin_action == "CREATE_ADMIN_ID":
            try:
                target_id = int(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid Telegram ID.", reply_markup=admin_input_menu())
                return
            if is_super_admin(target_id):
                await update.message.reply_text("❌ The Super Admin cannot be added as a secondary admin.", reply_markup=admin_input_menu())
                return
            existing = get_admin_by_telegram_id(target_id) if 'get_admin_by_telegram_id' in globals() else None
            if existing:
                await update.message.reply_text("❌ This Telegram ID is already an administrator.", reply_markup=admin_input_menu())
                return
            context.user_data["grant_target_id"] = target_id
            context.user_data["grant_mode"] = "CREATE"
            context.user_data["grant_selection"] = set()
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"🔐 SELECT GRANTS FOR ADMIN {target_id}\n\n"
                "Tap the permissions you want to give this administrator, then press Save Grants.",
                reply_markup=admin_grant_menu(),
            )
            return

        if admin_action == "EDIT_ADMIN_ID":
            try:
                target_id = int(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid Telegram ID.", reply_markup=admin_input_menu())
                return
            admin = get_admin_by_telegram_id(target_id)
            if not admin:
                await update.message.reply_text("❌ Administrator not found.", reply_markup=admin_input_menu())
                return
            context.user_data["grant_target_id"] = target_id
            context.user_data["grant_mode"] = "EDIT"
            context.user_data["grant_selection"] = set(get_admin_grants(target_id))
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✏️ EDIT GRANTS FOR {target_id}\n\nToggle permissions and press Save Grants.",
                reply_markup=admin_grant_menu(context.user_data["grant_selection"]),
            )
            return

        if admin_action == "TOGGLE_ADMIN_ID":
            try:
                target_id = int(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid Telegram ID.", reply_markup=admin_input_menu())
                return
            admin = get_admin_by_telegram_id(target_id)
            if not admin:
                await update.message.reply_text("❌ Administrator not found.", reply_markup=admin_input_menu())
                return
            new_active = not bool(admin["is_active"])
            set_admin_active(target_id, new_active)
            await log_admin_action(context, user.id, "ACTIVATE ADMIN" if new_active else "DEACTIVATE ADMIN", f"Active={new_active}", target_id)
            context.user_data.pop("admin_action", None)
            state = "ACTIVATED" if new_active else "DEACTIVATED"
            await update.message.reply_text(
                f"✅ ADMIN {state}\n\nTelegram ID: {target_id}",
                reply_markup=admin_management_menu(),
            )
            return

        if admin_action == "ADD_BINGO_ROOM":
            cleaned = text.replace(",", " ").split()
            if len(cleaned) != 2:
                await update.message.reply_text("❌ Enter: bet amount + cartel count. Example: 200 250", reply_markup=admin_input_menu())
                return
            try:
                bet = float(cleaned[0])
                cards = int(cleaned[1])
                if bet <= 0 or cards < 2:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Bet must be greater than 0 and cartels must be at least 2.", reply_markup=admin_input_menu())
                return
            room, status = create_bingo_room(bet, cards)
            if status == "already_exists":
                await update.message.reply_text("❌ A Bingo game with that bet amount already exists.", reply_markup=admin_input_menu())
                return
            if status != "created":
                await update.message.reply_text("❌ Could not create the Bingo game.", reply_markup=admin_input_menu())
                return
            await log_admin_action(context, user.id, "CREATE BINGO GAME", f"Bet={bet}; Cartels={cards}")
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                "✅ BINGO GAME CREATED\n\n"
                f"🆔 Game ID: {room['id']}\n"
                f"💵 Bet: {room['bet_amount']}\n"
                f"🎫 Cartels: {room['max_cards']}\n\n"
                "The Bingo card pool was expanded automatically if necessary.",
                reply_markup=bingo_admin_menu(),
            )
            return

        if admin_action == "EDIT_BINGO_ROOM_ID":
            try:
                room_id = int(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid game ID.", reply_markup=admin_input_menu())
                return
            room = get_bingo_room(room_id)
            if not room:
                await update.message.reply_text("❌ Bingo game not found.", reply_markup=admin_input_menu())
                return
            context.user_data["bingo_room_id"] = room_id
            context.user_data["admin_action"] = "EDIT_BINGO_ROOM_VALUES"
            await update.message.reply_text(
                "✏️ EDIT BINGO GAME\n\n"
                f"Current bet: {room['bet_amount']}\n"
                f"Current cartels: {room['max_cards']}\n\n"
                "Enter the new bet amount and cartel count together.\n"
                "Example: 25 300",
                reply_markup=admin_input_menu(),
            )
            return

        if admin_action == "EDIT_BINGO_ROOM_VALUES":
            cleaned = text.replace(",", " ").split()
            if len(cleaned) != 2:
                await update.message.reply_text("❌ Enter: new bet + new cartel count. Example: 25 300", reply_markup=admin_input_menu())
                return
            try:
                bet = float(cleaned[0])
                cards = int(cleaned[1])
                if bet <= 0 or cards < 2:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ Invalid bet or cartel count.", reply_markup=admin_input_menu())
                return
            room_id = context.user_data.get("bingo_room_id")
            room, status = update_bingo_room(room_id, bet_amount=bet, max_cards=cards)
            if status == "bet_exists":
                await update.message.reply_text("❌ Another Bingo game already uses that bet amount.", reply_markup=admin_input_menu())
                return
            if status != "updated":
                await update.message.reply_text("❌ Could not update the Bingo game.", reply_markup=admin_input_menu())
                return
            context.user_data.pop("admin_action", None)
            context.user_data.pop("bingo_room_id", None)
            await update.message.reply_text(
                "✅ BINGO GAME UPDATED\n\n"
                f"🆔 Game ID: {room['id']}\n"
                f"💵 New bet: {room['bet_amount']}\n"
                f"🎫 New cartels: {room['max_cards']}",
                reply_markup=bingo_admin_menu(),
            )
            return

        if admin_action == "TOGGLE_BINGO_ROOM_ID":
            try:
                room_id = int(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid game ID.", reply_markup=admin_input_menu())
                return
            room = get_bingo_room(room_id)
            if not room:
                await update.message.reply_text("❌ Bingo game not found.", reply_markup=admin_input_menu())
                return
            new_active = not bool(room["is_active"])
            room, status = update_bingo_room(room_id, is_active=new_active)
            context.user_data.pop("admin_action", None)
            state = "ENABLED" if new_active else "DISABLED"
            await update.message.reply_text(
                f"✅ BINGO GAME {state}\n\n"
                f"🆔 Game ID: {room_id}\n"
                f"💵 Bet: {room['bet_amount']}",
                reply_markup=bingo_admin_menu(),
            )
            return

        if admin_action == "DEMO_USER_ID":
            try:
                player_id = int(text)
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid Telegram ID. Enter the numeric Telegram ID.",
                    reply_markup=admin_input_menu(),
                )
                return

            player = get_user_by_telegram_id(player_id)
            if not player:
                await update.message.reply_text(
                    "❌ Player not found. Enter another Telegram ID.",
                    reply_markup=admin_input_menu(),
                )
                return

            context.user_data["demo_winnings_user_id"] = player_id
            context.user_data["admin_action"] = "DEMO_AMOUNT"
            await update.message.reply_text(
                "🎁 DEMO WINNINGS\n\n"
                f"Player: {player_id}\n"
                f"Current withdrawable: {player['withdrawable_balance']}\n\n"
                "Enter the amount to credit.\nExample: 500",
                reply_markup=admin_input_menu(),
            )
            return

        if admin_action == "DEMO_AMOUNT":
            try:
                amount = float(text)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid amount. Enter a positive number.",
                    reply_markup=admin_input_menu(),
                )
                return

            player_id = context.user_data.get("demo_winnings_user_id")
            try:
                player, status = add_demo_withdrawable_balance(player_id, amount)
            except Exception as e:
                logger.exception("Demo winnings credit error: %s", e)
                await update.message.reply_text(
                    "❌ Could not add demo winnings.",
                    reply_markup=admin_input_menu(),
                )
                return

            context.user_data.pop("admin_action", None)
            context.user_data.pop("demo_winnings_user_id", None)
            if status == "credited":
                total = get_total_balance(player)
                await update.message.reply_text(
                    "✅ DEMO WINNINGS ADDED\n\n"
                    f"👤 Player: {player_id}\n"
                    f"🎁 Added: {amount}\n"
                    f"🏆 Withdrawable: {player['withdrawable_balance']}\n"
                    f"💰 Total balance: {total}",
                    reply_markup=admin_menu(user.id),
                )
            else:
                await update.message.reply_text(
                    "❌ Could not add demo winnings.",
                    reply_markup=admin_menu(user.id),
                )
            return

        if admin_action == "BALANCE_USER_ID":
            try:
                player_id = int(text)
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid Telegram ID.",
                    reply_markup=admin_input_menu(),
                )
                return
            player = get_user_by_telegram_id(player_id)
            if not player:
                await update.message.reply_text(
                    "❌ Player not found.",
                    reply_markup=admin_input_menu(),
                )
                return
            context.user_data["balance_user_id"] = player_id
            context.user_data["admin_action"] = "BALANCE_TYPE"
            await update.message.reply_text(
                "💰 EDIT PLAYER BALANCE\n\n"
                f"Player: {player_id}\n"
                f"💳 Main / Deposited: {player['main_balance']}\n"
                f"🏆 Withdrawable: {player['withdrawable_balance']}\n\n"
                "Choose which balance you want to increase or decrease.",
                reply_markup=admin_balance_type_menu(),
            )
            return

        if admin_action == "BALANCE_TYPE":
            if text == "↩️ Admin Menu":
                context.user_data.pop("admin_action", None)
                context.user_data.pop("balance_user_id", None)
                await update.message.reply_text("👑 Admin menu.", reply_markup=admin_menu(user.id))
                return
            if text == "❌ Cancel Admin Action":
                context.user_data.pop("admin_action", None)
                context.user_data.pop("balance_user_id", None)
                await update.message.reply_text("❌ Admin action cancelled.", reply_markup=admin_menu(user.id))
                return
            if text not in ("💳 Main / Deposited", "🏆 Withdrawable"):
                await update.message.reply_text(
                    "Please choose Main / Deposited or Withdrawable from the menu.",
                    reply_markup=admin_balance_type_menu(),
                )
                return
            context.user_data["balance_type"] = (
                "main_balance" if text == "💳 Main / Deposited" else "withdrawable_balance"
            )
            context.user_data["admin_action"] = "BALANCE_AMOUNT"
            player_id = context.user_data.get("balance_user_id")
            player = get_user_by_telegram_id(player_id)
            label = "Main / Deposited" if text == "💳 Main / Deposited" else "Withdrawable"
            current = player["main_balance"] if text == "💳 Main / Deposited" else player["withdrawable_balance"]
            await update.message.reply_text(
                "💰 BALANCE ADJUSTMENT\n\n"
                f"Player: {player_id}\n"
                f"Balance: {label}\n"
                f"Current: {current}\n\n"
                "Enter adjustment amount.\n"
                "Examples:\n100 = increase by 100\n-50 = decrease by 50",
                reply_markup=admin_input_menu(),
            )
            return

        if admin_action == "BALANCE_AMOUNT":
            try:
                amount = float(text)
                if amount == 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "❌ Enter a non-zero number, for example 100 or -50.",
                    reply_markup=admin_input_menu(),
                )
                return
            player_id = context.user_data.get("balance_user_id")
            balance_type = context.user_data.get("balance_type")
            try:
                if balance_type == "main_balance":
                    player, status = adjust_demo_main_balance(player_id, amount)
                    label = "Main / Deposited"
                    negative_status = "insufficient_main"
                else:
                    player, status = adjust_demo_withdrawable_balance(player_id, amount)
                    label = "Withdrawable"
                    negative_status = "insufficient_withdrawable"
            except Exception as e:
                logger.exception("Player balance adjustment error: %s", e)
                await update.message.reply_text(
                    "❌ Could not update player balance.",
                    reply_markup=admin_input_menu(),
                )
                return
            if status == negative_status:
                await update.message.reply_text(
                    f"❌ This decrease would make the player's {label.lower()} balance negative.",
                    reply_markup=admin_input_menu(),
                )
                return
            if status == "adjusted":
                await log_admin_action(context, user.id, "EDIT PLAYER BALANCE", f"Type={label}; Adjustment={amount}", player_id)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("balance_user_id", None)
            context.user_data.pop("balance_type", None)
            if status == "adjusted":
                await update.message.reply_text(
                    "✅ PLAYER BALANCE UPDATED\n\n"
                    f"👤 Player: {player_id}\n"
                    f"💰 Balance type: {label}\n"
                    f"📈 Adjustment: {amount}\n"
                    f"💳 Main / Deposited: {player['main_balance']}\n"
                    f"🎁 Bonus: {player['bonus_balance']}\n"
                    f"🏆 Withdrawable: {player['withdrawable_balance']}\n"
                    f"💰 Total balance: {get_total_balance(player)}",
                    reply_markup=admin_menu(user.id),
                )
            else:
                await update.message.reply_text(
                    "❌ Could not update player balance.",
                    reply_markup=admin_menu(user.id),
                )
            return

        if admin_action == "BONUS_USER_ID":
            try:
                player_id = int(text)
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid Telegram ID.",
                    reply_markup=admin_input_menu(),
                )
                return
            player = get_user_by_telegram_id(player_id)
            if not player:
                await update.message.reply_text(
                    "❌ Player not found.",
                    reply_markup=admin_input_menu(),
                )
                return
            context.user_data["bonus_user_id"] = player_id
            context.user_data["admin_action"] = "BONUS_AMOUNT"
            await update.message.reply_text(
                "🪙 EDIT PLAYER BONUS BALANCE\n\n"
                f"Player: {player_id}\n"
                f"Current bonus balance: {player['bonus_balance']}\n\n"
                "Enter adjustment amount.\n"
                "Examples:\n100 = increase by 100\n-50 = decrease by 50",
                reply_markup=admin_input_menu(),
            )
            return

        if admin_action == "BONUS_AMOUNT":
            try:
                amount = float(text)
                if amount == 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "❌ Enter a non-zero number, for example 100 or -50.",
                    reply_markup=admin_input_menu(),
                )
                return
            player_id = context.user_data.get("bonus_user_id")
            player, status = adjust_demo_bonus_balance(player_id, amount)
            if status == "insufficient_bonus":
                await update.message.reply_text(
                    "❌ That decrease would make the player's bonus balance negative.",
                    reply_markup=admin_input_menu(),
                )
                return
            if status == "adjusted":
                await log_admin_action(context, user.id, "EDIT PLAYER BONUS", f"Adjustment={amount}", player_id)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("bonus_user_id", None)
            if status == "adjusted":
                await update.message.reply_text(
                    "✅ PLAYER BONUS BALANCE UPDATED\n\n"
                    f"👤 Player: {player_id}\n"
                    f"Adjustment: {amount}\n"
                    f"New bonus balance: {player['bonus_balance']}",
                    reply_markup=admin_menu(user.id),
                )
            else:
                await update.message.reply_text(
                    "❌ Could not update player bonus balance.",
                    reply_markup=admin_menu(user.id),
                )
            return

        if admin_action in (
            "SET_REGISTRATION_BONUS",
            "SET_REFERRAL_BONUS",
            "SET_FIRST_DEPOSIT_REQUIRED",
            "SET_BINGO_COMMISSION",
        ):
            try:
                value = float(text)
                if value < 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "❌ Enter a number that is 0 or greater.",
                    reply_markup=admin_input_menu(),
                )
                return

            if admin_action == "SET_BINGO_COMMISSION" and value > 100:
                await update.message.reply_text(
                    "❌ Commission must be between 0% and 100%.",
                    reply_markup=admin_input_menu(),
                )
                return

            if admin_action == "SET_BINGO_COMMISSION":
                success, status = set_bingo_commission_percent(value)
                if not success:
                    await update.message.reply_text(
                        "❌ Commission must be between 0% and 100%.",
                        reply_markup=admin_input_menu(),
                    )
                    return

                await log_admin_action(context, user.id, "EDIT GAME COMMISSION", f"Bingo commission={value}%")
                context.user_data.pop("admin_action", None)
                await update.message.reply_text(
                    "✅ GAME COMMISSION UPDATED\n\n"
                    f"🎯 Bingo commission: {value}%\n\n"
                    "This percentage will be used for new Bingo rounds.",
                    reply_markup=admin_settings_menu(user.id),
                )
                return

            key_map = {
                "SET_REGISTRATION_BONUS": "registration_bonus",
                "SET_REFERRAL_BONUS": "referral_bonus",
                "SET_FIRST_DEPOSIT_REQUIRED": "first_deposit_required",
            }
            label_map = {
                "SET_REGISTRATION_BONUS": "Registration bonus",
                "SET_REFERRAL_BONUS": "Referral bonus",
                "SET_FIRST_DEPOSIT_REQUIRED": "First withdrawal deposit requirement",
            }
            key = key_map[admin_action]
            set_system_setting(key, value)
            await log_admin_action(context, user.id, "EDIT ADMIN SETTING", f"{label_map[admin_action]}={value}")
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ {label_map[admin_action]} updated to {value}.",
                reply_markup=admin_settings_menu(user.id),
            )
            return

        if admin_action == "SET_WITHDRAWAL_LIMITS":
            cleaned = text.replace(",", " ").split()
            if len(cleaned) != 2:
                await update.message.reply_text(
                    "❌ Enter both values together.\nExample: 100 5000",
                    reply_markup=admin_input_menu(),
                )
                return
            try:
                minimum = float(cleaned[0])
                maximum = float(cleaned[1])
                if minimum < 0 or maximum <= 0 or maximum < minimum:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid limits. Maximum must be greater than or equal to minimum.",
                    reply_markup=admin_input_menu(),
                )
                return

            set_system_setting("min_withdrawal", minimum)
            set_system_setting("max_withdrawal", maximum)
            await log_admin_action(context, user.id, "EDIT WITHDRAWAL LIMITS", f"Minimum={minimum}; Maximum={maximum}")
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                "✅ WITHDRAWAL LIMITS UPDATED\n\n"
                f"⬇️ Minimum: {minimum}\n"
                f"⬆️ Maximum: {maximum}",
                reply_markup=admin_settings_menu(user.id),
            )
            return

    # --------------------------------------------------------
    # ADMIN MENU NAVIGATION
    # --------------------------------------------------------
    if is_admin(user.id):
        if text == "🎁 Add Demo Winnings" and can_admin(user.id, "player_balance"):
            context.user_data["admin_action"] = "DEMO_USER_ID"
            await update.message.reply_text(
                "🎁 ADD DEMO WITHDRAWABLE BALANCE\n\n"
                "Enter the player Telegram ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "💰 Edit Player Balance" and can_admin(user.id, "player_balance"):
            context.user_data["admin_action"] = "BALANCE_USER_ID"
            await update.message.reply_text(
                "💰 EDIT PLAYER BALANCE\n\nEnter the player's Telegram ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "⚙️ Admin Settings" and (can_admin(user.id, "settings") or can_admin(user.id, "commission")):
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                "⚙️ ADMIN SETTINGS\n\nChoose the setting you want to edit.",
                reply_markup=admin_settings_menu(user.id),
            )
            return

        if text == "🪙 Edit Player Bonus" and can_admin(user.id, "player_bonus"):
            context.user_data["admin_action"] = "BONUS_USER_ID"
            await update.message.reply_text(
                "🪙 EDIT PLAYER BONUS BALANCE\n\nEnter the player's Telegram ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "🎁 Registration Bonus" and can_admin(user.id, "settings"):
            current = get_system_setting_float("registration_bonus", REGISTRATION_BONUS)
            context.user_data["admin_action"] = "SET_REGISTRATION_BONUS"
            await update.message.reply_text(
                f"🎁 Current registration bonus: {current}\n\nEnter the new value.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "👥 Referral Bonus" and can_admin(user.id, "settings"):
            current = get_system_setting_float("referral_bonus", REFERRAL_BONUS)
            context.user_data["admin_action"] = "SET_REFERRAL_BONUS"
            await update.message.reply_text(
                f"👥 Current referral bonus: {current}\n\nEnter the new value.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "💳 First Deposit Requirement" and can_admin(user.id, "settings"):
            current = get_system_setting_float("first_deposit_required", 200)
            context.user_data["admin_action"] = "SET_FIRST_DEPOSIT_REQUIRED"
            await update.message.reply_text(
                "💳 FIRST WITHDRAWAL DEPOSIT REQUIREMENT\n\n"
                f"Current value: {current}\n\nEnter the new value.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "🎯 Game Commission" and can_admin(user.id, "commission"):
            current = get_bingo_commission_percent()
            context.user_data["admin_action"] = "SET_BINGO_COMMISSION"
            await update.message.reply_text(
                "🎯 GAME COMMISSION\n\n"
                f"Current Bingo commission: {current}%\n\n"
                "Enter the new commission percentage.\n"
                "Example: 10\n\n"
                "This is the percentage the Super Admin receives from each Bingo game pot.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "💸 Withdrawal Limits" and can_admin(user.id, "settings"):
            minimum = get_system_setting_float("min_withdrawal", 100)
            maximum = get_system_setting_float("max_withdrawal", 10000)
            context.user_data["admin_action"] = "SET_WITHDRAWAL_LIMITS"
            await update.message.reply_text(
                "💸 WITHDRAWAL LIMITS\n\n"
                f"Current minimum: {minimum}\n"
                f"Current maximum: {maximum}\n\n"
                "Enter the new minimum and maximum together.\nExample: 100 5000",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "🎱 Bingo Game Settings" and can_admin(user.id, "bingo_rooms"):
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                "🎱 BINGO GAME SETTINGS\n\nManage bet amounts and the number of available cartels for each game.",
                reply_markup=bingo_admin_menu(),
            )
            return

        if text == "📋 List Bingo Games" and can_admin(user.id, "bingo_rooms"):
            await update.message.reply_text(
                format_bingo_rooms(get_bingo_rooms(active_only=False)),
                reply_markup=bingo_admin_menu(),
            )
            return

        if text == "➕ Add Bet Game" and can_admin(user.id, "bingo_rooms"):
            context.user_data["admin_action"] = "ADD_BINGO_ROOM"
            await update.message.reply_text(
                "➕ ADD BINGO BET GAME\n\n"
                "Enter: bet amount + number of cartels\n"
                "Example: 200 250\n\n"
                "This creates a new Bingo game with a 200 bet and 250 available cartels.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "✏️ Edit Bingo Game" and can_admin(user.id, "bingo_rooms"):
            context.user_data["admin_action"] = "EDIT_BINGO_ROOM_ID"
            await update.message.reply_text(
                "✏️ EDIT BINGO GAME\n\n"
                "Enter the Bingo game ID. Use 📋 List Bingo Games to see the IDs.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "🔄 Enable / Disable Game" and can_admin(user.id, "bingo_rooms"):
            context.user_data["admin_action"] = "TOGGLE_BINGO_ROOM_ID"
            await update.message.reply_text(
                "🔄 ENABLE / DISABLE BINGO GAME\n\n"
                "Enter the Bingo game ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "👑 Manage Admins" and is_super_admin(user.id):
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                "👑 ADMIN MANAGEMENT\n\nCreate administrators and give each one only the permissions they need.",
                reply_markup=admin_management_menu(),
            )
            return

        if text == "➕ Create Admin" and is_super_admin(user.id):
            context.user_data["admin_action"] = "CREATE_ADMIN_ID"
            await update.message.reply_text(
                "➕ CREATE ADMIN\n\nEnter the new administrator's Telegram ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "👥 List Admins" and is_super_admin(user.id):
            admins = get_all_admins()
            if not admins:
                await update.message.reply_text("👥 ADMINS\n\nNo additional administrators have been created.", reply_markup=admin_management_menu())
            else:
                buttons = []
                for admin in admins:
                    status = "🟢" if int(admin["is_active"]) else "🔴"
                    buttons.append([InlineKeyboardButton(f"{status} Admin {admin['telegram_user_id']}", callback_data=f"admin_detail:{admin['telegram_user_id']}")])
                await update.message.reply_text("👥 ADMIN LIST\n\nSelect an administrator to view full details and his own activity log.", reply_markup=InlineKeyboardMarkup(buttons))
            return

        if text == "✏️ Edit Admin Grants" and is_super_admin(user.id):
            context.user_data["admin_action"] = "EDIT_ADMIN_ID"
            await update.message.reply_text(
                "✏️ EDIT ADMIN GRANTS\n\nEnter the administrator's Telegram ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "🔄 Activate / Deactivate Admin" and is_super_admin(user.id):
            context.user_data["admin_action"] = "TOGGLE_ADMIN_ID"
            await update.message.reply_text(
                "🔄 ADMIN STATUS\n\nEnter the administrator's Telegram ID.",
                reply_markup=admin_input_menu(),
            )
            return

        if text == "↩️ Admin Menu":
            await update.message.reply_text("👑 Admin menu.", reply_markup=admin_menu(user.id))
            return

        if text == "📊 Admin Dashboard" and can_admin(user.id, "dashboard"):
            await admin_dashboard(update, context)
            return

        if text == "💳 Pending Deposits" and can_admin(user.id, "deposits"):
            await admin_pending_deposits(update, context)
            return

        if text == "💸 Pending Withdrawals" and can_admin(user.id, "withdrawals"):
            await admin_pending_withdrawals(update, context)
            return

        if text == "🔄 Refresh Admin" and can_admin(user.id, "dashboard"):
            await admin_dashboard(update, context)
            return

        if text == "📋 Admin Activity Log" and is_super_admin(user.id):
            logs = get_admin_activity(100)
            if not logs:
                body = "📋 ADMIN ACTIVITY LOG\n\nNo administrator activity has been recorded yet."
            else:
                lines = ["📋 ADMIN ACTIVITY LOG", ""]
                for item in logs:
                    lines.append(
                        f"#{item['id']} | {item['created_at']}\n"
                        f"👤 Admin: {item['admin_telegram_id']}\n"
                        f"📝 {item['action']}"
                        + (f"\n🎯 Target: {item['target_telegram_id']}" if item['target_telegram_id'] else "")
                        + (f"\n📌 {item['details']}" if item['details'] else "")
                    )
                    lines.append("")
                body = "\n".join(lines)
            await update.message.reply_text(body, reply_markup=admin_management_menu())
            return

        if text == "🚪 Exit Admin":
            for key in ("admin_action", "demo_winnings_user_id", "bonus_user_id", "balance_user_id", "balance_type"):
                context.user_data.pop(key, None)
            await update.message.reply_text(
                "🚪 Admin mode closed.\n\nYou are back in the player menu.",
                reply_markup=registered_menu(user.id),
            )
            return

    # --------------------------------------------------------
    # DEPOSIT AMOUNT -> TRANSACTION ID
    # --------------------------------------------------------
    if wallet_action == "DEPOSIT_AMOUNT":
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount.\n\nEnter a positive number.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        context.user_data["deposit_amount"] = amount
        context.user_data["wallet_action"] = "DEPOSIT_TRANSACTION_ID"
        await update.message.reply_text(
            "🧾 DEMO TRANSACTION ID\n\n"
            f"💰 Deposit amount: {amount}\n\n"
            "Now enter the demo transaction ID/reference from your demo transfer.",
            reply_markup=wallet_input_reply_keyboard(),
        )
        return

    # --------------------------------------------------------
    # DEPOSIT TRANSACTION ID -> CREATE REQUEST
    # --------------------------------------------------------
    if wallet_action == "DEPOSIT_TRANSACTION_ID":
        transaction_id = text.strip()
        if len(transaction_id) < 3:
            await update.message.reply_text(
                "❌ Transaction ID is too short. Please enter a valid demo transaction ID.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        bank_id = context.user_data.get("deposit_bank_id")
        amount = context.user_data.get("deposit_amount")
        bank = get_demo_bank(bank_id)
        if not bank or amount is None:
            await update.message.reply_text(
                "❌ Deposit information is incomplete. Please start again.",
                reply_markup=registered_menu(user.id),
            )
            for key in ("wallet_action", "deposit_bank_id", "deposit_amount", "deposit_transaction_id"):
                context.user_data.pop(key, None)
            return

        request_id, status = create_deposit_request(
            user.id,
            bank_id,
            amount,
            transaction_id,
        )

        if status == "pending_same_bank":
            await update.message.reply_text(
                "⚠️ You already have a pending deposit request for this bank.\n\n"
                "Wait for that request to be processed, or create a new deposit using a different demo bank.",
                reply_markup=registered_menu(user.id),
            )
        elif status == "created":
            await update.message.reply_text(
                "✅ DEPOSIT REQUEST SUBMITTED!\n\n"
                f"🏦 Bank: {bank['bank_name']}\n"
                f"💰 Amount: {amount}\n"
                f"🧾 Transaction ID: {transaction_id}\n"
                f"🆔 Request: #{request_id}\n\n"
                "⏳ Status: PENDING\n\n"
                "A Super Admin has been notified and must approve the request before the amount is added to your balance.",
                reply_markup=registered_menu(user.id),
            )
            await notify_admin_deposit(
                context,
                user,
                bank,
                request_id,
                amount,
                transaction_id,
            )
        else:
            await update.message.reply_text(
                "❌ Could not create deposit request.",
                reply_markup=registered_menu(user.id),
            )

        for key in ("wallet_action", "deposit_bank_id", "deposit_amount", "deposit_transaction_id"):
            context.user_data.pop(key, None)
        return

    # --------------------------------------------------------
    # WITHDRAW ACCOUNT NUMBER
    # --------------------------------------------------------
    if wallet_action == "WITHDRAW_ACCOUNT_NUMBER":
        account_number = text.strip()
        if len(account_number) < 3:
            await update.message.reply_text(
                "❌ Please enter a valid demo account number.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        context.user_data["withdraw_account_number"] = account_number
        context.user_data["wallet_action"] = "WITHDRAW_ACCOUNT_NAME"
        await update.message.reply_text(
            "👤 DEMO ACCOUNT NAME\n\n"
            "Now enter the name registered on this demo bank account.",
            reply_markup=wallet_input_reply_keyboard(),
        )
        return

    # --------------------------------------------------------
    # WITHDRAW ACCOUNT NAME
    # --------------------------------------------------------
    if wallet_action == "WITHDRAW_ACCOUNT_NAME":
        account_name = text.strip()
        if not account_name:
            await update.message.reply_text(
                "❌ Account name cannot be empty.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        context.user_data["withdraw_account_name"] = account_name
        context.user_data["wallet_action"] = "WITHDRAW_AMOUNT"
        bank_id = context.user_data.get("withdraw_bank_id")
        bank = get_demo_bank(bank_id)
        bank_name = bank["bank_name"] if bank else "Selected demo bank"
        minimum = get_system_setting_float("min_withdrawal", 100)
        maximum = get_system_setting_float("max_withdrawal", 10000)
        await update.message.reply_text(
            "💰 WITHDRAWAL AMOUNT\n\n"
            f"🏦 Bank: {bank_name}\n"
            f"👤 Account Name: {account_name}\n"
            f"⬇️ Minimum: {minimum}\n"
            f"⬆️ Maximum: {maximum}\n\n"
            "Now enter the amount you want to withdraw.",
            reply_markup=wallet_input_reply_keyboard(),
        )
        return

    # --------------------------------------------------------
    # WITHDRAW AMOUNT
    # --------------------------------------------------------
    if wallet_action == "WITHDRAW_AMOUNT":
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount.\n\nEnter a positive number.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        user_account = get_user_by_telegram_id(user.id)
        if not user_account:
            await update.message.reply_text(
                "❌ Account not found.",
                reply_markup=registered_menu(user.id),
            )
            return

        available = float(user_account["withdrawable_balance"])
        minimum = get_system_setting_float("min_withdrawal", 100)
        maximum = get_system_setting_float("max_withdrawal", 10000)
        first_required = get_system_setting_float("first_deposit_required", 200)

        if float(user_account["total_withdrawn"] or 0) <= 0 and float(user_account["total_deposited"] or 0) < first_required:
            await update.message.reply_text(
                f"❌ First withdrawal requires at least {first_required} in approved demo deposits.",
                reply_markup=registered_menu(user.id),
            )
            return

        if amount < minimum:
            await update.message.reply_text(
                f"❌ Minimum withdrawal is {minimum}.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        if maximum > 0 and amount > maximum:
            await update.message.reply_text(
                f"❌ Maximum withdrawal is {maximum}.",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        if amount > available:
            await update.message.reply_text(
                "❌ Insufficient withdrawable balance.\n\n"
                f"Available: {available}",
                reply_markup=wallet_input_reply_keyboard(),
            )
            return

        bank_id = context.user_data.get("withdraw_bank_id")
        account_number = context.user_data.get("withdraw_account_number")
        account_name = context.user_data.get("withdraw_account_name")
        if not bank_id or not account_number or not account_name:
            await update.message.reply_text(
                "❌ Withdrawal information is incomplete. Please start again.",
                reply_markup=registered_menu(user.id),
            )
            for key in (
                "wallet_action", "withdraw_bank_id", "withdraw_amount",
                "withdraw_account_number", "withdraw_account_name",
            ):
                context.user_data.pop(key, None)
            return

        request_id, status = create_withdrawal_request(
            user.id,
            bank_id,
            amount,
            account_number,
            account_name,
        )

        if status == "created":
            bank = get_demo_bank(bank_id)
            bank_name = bank["bank_name"] if bank else "Demo Bank"
            await update.message.reply_text(
                "✅ WITHDRAWAL REQUEST SUBMITTED!\n\n"
                f"🏦 Bank: {bank_name}\n"
                f"💰 Amount: {amount}\n"
                f"👤 Account Name: {account_name}\n"
                f"🔢 Account Number: {account_number}\n"
                f"🆔 Request: #{request_id}\n\n"
                "⏳ Status: PENDING\n\n"
                "The amount has been reserved from your withdrawable balance.\n"
                "A Super Admin has been notified.",
                reply_markup=registered_menu(user.id),
            )
            await notify_admin_withdrawal(
                context,
                user,
                bank,
                request_id,
                amount,
                account_number,
                account_name,
            )
        elif status == "pending_exists":
            await update.message.reply_text(
                "⚠️ You already have a pending withdrawal request.",
                reply_markup=registered_menu(user.id),
            )
        elif status == "first_deposit_required":
            await update.message.reply_text(
                f"❌ First withdrawal requires at least {first_required} in approved demo deposits.",
                reply_markup=registered_menu(user.id),
            )
        elif status == "below_minimum":
            await update.message.reply_text(
                f"❌ Minimum withdrawal is {minimum}.",
                reply_markup=registered_menu(user.id),
            )
        elif status == "above_maximum":
            await update.message.reply_text(
                f"❌ Maximum withdrawal is {maximum}.",
                reply_markup=registered_menu(user.id),
            )
        else:
            await update.message.reply_text(
                "❌ Withdrawal request failed.",
                reply_markup=registered_menu(user.id),
            )

        for key in (
            "wallet_action", "withdraw_bank_id", "withdraw_amount",
            "withdraw_account_number", "withdraw_account_name",
        ):
            context.user_data.pop(key, None)
        return

    # --------------------------------------------------------
    # NORMAL PLAYER MENU
    # --------------------------------------------------------
    if text == "💰 Balance":
        await balance(update)
        return
    if text == "👤 Profile":
        await profile(update)
        return
    if text == "🎮 Games":
        await games(update)
        return
    if text == "💳 Deposit":
        await start_deposit(update, context)
        return
    if text == "💸 Withdraw":
        await start_withdraw(update, context)
        return
    if text == "👥 Invite":
        await invite(update)
        return
    if text == "📜 Transactions":
        await transactions(update)
        return
    if text == "⏳ Pending Requests":
        await show_player_pending_requests(update)
        return
    if text == "🆘 Support":
        await support(update)
        return
    if text == "👑 Open Admin" and is_admin(user.id):
        await update.message.reply_text(
            "👑 ADMIN MODE\n\nChoose an admin option.",
            reply_markup=admin_menu(user.id),
        )
        return

    await update.message.reply_text(
        "Please choose an option from the menu below.",
        reply_markup=registered_menu(user.id),
    )



# ============================================================
# /ADMIN COMMAND
# ============================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user


    if not user or not get_user_by_telegram_id(user.id):
        await update.message.reply_text(
            "📱 Register as a player first with /start. Administrator access is enabled only after player registration."
        )
        return


    if not is_admin(user.id):

        await update.message.reply_text(
            "⛔ Access denied.\n\n"
            "This command is only available to administrators."
        )

        return


    await update.message.reply_text(
        "👑 SUPER ADMIN MODE\n\n"
        "Choose an admin option.",
        reply_markup=admin_menu(user.id),
    )


# ============================================================
# MINI APP URL
# ============================================================
# Temporary URL for development. Change this when the Mini App
# is deployed to GitHub Pages.
MINI_APP_URL = "https://finbase18-lab.github.io/Bingo_frontend/"


# ============================================================
# PLAY COMMAND
# ============================================================
async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not get_user_by_telegram_id(user.id):
        await update.message.reply_text(
            "📱 Please register first with /start before opening Bingo."
        )
        return

    keyboard = [[
        InlineKeyboardButton(
            "🎮 PLAY BINGO",
            web_app=WebAppInfo(url=MINI_APP_URL),
        )
    ]]
    await update.message.reply_text(
        "🎮 BINGO MINI APP\n\nTap the button below to open the game lobby.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# POST INIT
# ============================================================

async def post_init(
    application: Application
):

    global BOT_USERNAME


    try:

        me = await application.bot.get_me()

        BOT_USERNAME = me.username

        logger.info(
            "Bot username: @%s",
            BOT_USERNAME
        )

    except Exception as e:

        logger.warning(
            "Could not get bot username: %s",
            e
        )


    # Configure Telegram's native menu button. The player no longer receives
    # a persistent ReplyKeyboard; Telegram shows these commands from the
    # menu button beside the message input field.
    try:
        await application.bot.set_my_commands([
            BotCommand("start", "Start / register"),
            BotCommand("play", "🎮 Play Games"),
            BotCommand("balance", "View balance"),
            BotCommand("profile", "View profile"),
            BotCommand("games", "Open games"),
            BotCommand("deposit", "Make a demo deposit"),
            BotCommand("withdraw", "Make a demo withdrawal"),
            BotCommand("invite", "Invite friends"),
            BotCommand("transactions", "View transactions"),
            BotCommand("pending", "View pending requests"),
            BotCommand("support", "Contact support"),
            BotCommand("admin", "Open admin panel"),
        ])
        # Keep Telegram's normal default Menu button.
        # Telegram opens and hides the command list itself.
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonCommands()
        )
        logger.info("Telegram default command menu configured.")
    except Exception as e:
        logger.warning("Could not configure Telegram native menu: %s", e)


# ============================================================
# TELEGRAM NATIVE MENU COMMANDS
# ============================================================

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await balance(update)

async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await profile(update)

async def cmd_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await games(update)

async def cmd_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_deposit(update, context)

async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_withdraw(update, context)

async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await invite(update)

async def cmd_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await transactions(update)

async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_player_pending_requests(update)

async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support(update)


# ============================================================
# SHOW MENU COMMAND
# ============================================================

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and get_user_by_telegram_id(user.id):
        await update.message.reply_text(
            "☰ Use Telegram's menu button beside the message box to open the bot menu."
        )
    else:
        await update.message.reply_text("Please use /start first.")


# ============================================================
# MAIN
# ============================================================

def main():

    init_database()

    # Create editable settings once. Existing admin-edited values are preserved.
    ensure_system_setting("registration_bonus", REGISTRATION_BONUS)
    ensure_system_setting("referral_bonus", REFERRAL_BONUS)
    ensure_system_setting("first_deposit_required", 200)
    ensure_system_setting("bingo_commission_percent", 10)
    ensure_system_setting("min_withdrawal", 100)
    ensure_system_setting("max_withdrawal", 10000)


    if not BOT_TOKEN:

        print(
            "ERROR: BOT_TOKEN is missing."
        )

        return


    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )


    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "menu",
            show_menu
        )
    )

    # Play command opens the Mini App.
    application.add_handler(CommandHandler("play", cmd_play))

    # Player commands shown by Telegram's native menu button.
    application.add_handler(CommandHandler("balance", cmd_balance))
    application.add_handler(CommandHandler("profile", cmd_profile))
    application.add_handler(CommandHandler("games", cmd_games))
    application.add_handler(CommandHandler("deposit", cmd_deposit))
    application.add_handler(CommandHandler("withdraw", cmd_withdraw))
    application.add_handler(CommandHandler("invite", cmd_invite))
    application.add_handler(CommandHandler("transactions", cmd_transactions))
    application.add_handler(CommandHandler("pending", cmd_pending))
    application.add_handler(CommandHandler("support", cmd_support))


    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )


    # --------------------------------------------------------
    # CONTACT
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.CONTACT,
            contact_received
        )
    )


    # --------------------------------------------------------
    # INLINE CALLBACKS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            deposit_bank_callback,
            pattern=r"^deposit_bank:"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            withdraw_bank_callback,
            pattern=r"^withdraw_bank:"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            admin_deposit_approve_callback,
            pattern=r"^admin_deposit_approve:"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            admin_deposit_reject_callback,
            pattern=r"^admin_deposit_reject:"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            admin_withdraw_approve_callback,
            pattern=r"^admin_withdraw_approve:"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            admin_withdraw_reject_callback,
            pattern=r"^admin_withdraw_reject:"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            wallet_cancel_callback,
            pattern=r"^wallet_cancel$"
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            admin_grant_callback,
            pattern=r"^admin_grant_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_detail_callback,
            pattern=r"^admin_detail:"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_list_callback,
            pattern=r"^admin_list$"
        )
    )


    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )


    print()
    print("========================================")
    print("       BINGO TELEGRAM BOT")
    print("========================================")
    print("Bot is running...")
    print("Super Admin system enabled.")
    print("Deposit approval enabled.")
    print("Withdrawal approval enabled.")
    print("========================================")
    print()


    application.run_polling()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()