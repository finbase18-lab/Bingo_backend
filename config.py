import os


# ============================================================
# TELEGRAM
# ============================================================

# Render will provide TELEGRAM_BOT_TOKEN.
# For local Pydroid testing, you can temporarily put your token
# in an environment variable or use the fallback value.
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


# ============================================================
# SUPER ADMIN
# ============================================================

# Put your Telegram numeric user ID in Render as:
#
# SUPER_ADMIN_ID = 123456789
#
# Never put the real ID in GitHub if you want it kept private.
try:
    SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0"))
except ValueError:
    SUPER_ADMIN_ID = 0


# ============================================================
# DEMO SETTINGS
# ============================================================

REGISTRATION_BONUS = float(
    os.getenv("REGISTRATION_BONUS", "100")
)

REFERRAL_BONUS = float(
    os.getenv("REFERRAL_BONUS", "50")
)