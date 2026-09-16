import hashlib
import hmac
import json
import os
import time
from threading import Lock
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from config import BOT_TOKEN
except Exception:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

from database import (
    init_database,
    get_user_by_telegram_id,
    get_total_balance,
    get_user_profile,
    get_bingo_dashboard_data,
    create_bingo_round,
    get_bingo_round,
    get_bingo_round_players,
    get_available_bingo_cards,
    join_bingo_round,
    get_bingo_calls,
    get_remaining_bingo_countdown,
    start_bingo_playing,
    call_next_bingo_number,
    find_bingo_winners,
    finish_bingo_round_with_winners,
    set_bingo_round_result,
    finish_bingo_round,
    calculate_bingo_round_financials,
    get_enabled_bingo_patterns,
    get_all_bingo_patterns,
    set_bingo_pattern_enabled,
    is_admin_user,
    has_admin_grant,
    get_admin_grants,
    get_admin_statistics,
    get_pending_deposits,
    get_pending_withdrawals,
    approve_deposit,
    reject_deposit,
    approve_withdrawal,
    reject_withdrawal,
    get_all_admins,
    get_admin_activity,
    get_bingo_winners,
    get_all_player_telegram_ids,
    adjust_demo_bonus_balance,
    adjust_demo_main_balance,
    adjust_demo_withdrawable_balance,
    set_system_setting,
    get_system_setting_float,
    create_bingo_room,
    update_bingo_room,
    create_admin_user,
    set_admin_grants,
    set_admin_active,
    ADMIN_GRANTS,
    get_bingo_commission_percent,
    set_bingo_commission_percent,
    get_demo_banks,
    create_deposit_request,
    get_user_deposit_requests,
    create_withdrawal_request,
    get_user_withdrawal_requests,
    DATABASE_FILE,
)


app = FastAPI(title="Bingo Mini App Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One backend instance is enough for the first demo deployment. This prevents
# two simultaneous browser polls from drawing two Bingo numbers at once.
engine_lock = Lock()
CALL_INTERVAL_SECONDS = 5
INIT_DATA_MAX_AGE_SECONDS = 86400


class JoinRequest(BaseModel):
    card_id: int


class DepositRequestBody(BaseModel):
    bank_id: int
    amount: float
    transaction_id: str


class WithdrawalRequestBody(BaseModel):
    bank_id: int
    amount: float
    account_number: str
    account_name: str


def _telegram_data_check_string(init_data: str):
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Telegram hash is missing")

    check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Telegram hash validation failed")

    auth_date = data.get("auth_date")
    if auth_date:
        try:
            age = time.time() - int(auth_date)
            if age < -300 or age > INIT_DATA_MAX_AGE_SECONDS:
                raise ValueError("Telegram initData has expired")
        except ValueError:
            raise
        except Exception:
            raise ValueError("Invalid Telegram auth_date")

    user_json = data.get("user")
    if not user_json:
        raise ValueError("Telegram user is missing")

    user = json.loads(user_json)
    if not user.get("id"):
        raise ValueError("Telegram user ID is missing")
    return user


def authenticate(init_data: str):
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN is not configured")
    try:
        telegram_user = _telegram_data_check_string(init_data)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    account = get_user_by_telegram_id(int(telegram_user["id"]))
    if not account:
        raise HTTPException(status_code=403, detail="Player is not registered")
    if int(account["is_blocked"] or 0):
        raise HTTPException(status_code=403, detail="Player account is blocked")
    return account, telegram_user


def auth_from_header(x_telegram_init_data: str | None):
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Telegram authentication data is missing")
    return authenticate(x_telegram_init_data)


def row_to_dict(row):
    return dict(row) if row is not None else None


def user_payload(account):
    total = get_total_balance(account)
    return {
        "id": int(account["id"]),
        "telegram_user_id": int(account["telegram_user_id"]),
        "username": account["username"],
        "first_name": account["first_name"],
        "last_name": account["last_name"],
        "display_name": (
            (account["first_name"] or "") + " " + (account["last_name"] or "")
        ).strip() or account["username"] or "Player",
        "balance": round(float(total), 2),
        "main_balance": round(float(account["main_balance"] or 0), 2),
        "bonus_balance": round(float(account["bonus_balance"] or 0), 2),
        "withdrawable_balance": round(float(account["withdrawable_balance"] or 0), 2),
    }


def room_payload(row):
    item = row_to_dict(row)
    if not item:
        return None
    item["room_id"] = int(item["room_id"])
    item["bet_amount"] = round(float(item["bet_amount"] or 0), 2)
    item["active_players"] = int(item["active_players"] or 0)
    item["selected_cards"] = int(item["selected_cards"] or 0)
    item["max_cards"] = int(item["max_cards"] or 0)
    item["min_players"] = int(item["min_players"] or 0)
    item["max_players"] = int(item["max_players"] or 0)
    item["countdown_seconds"] = int(item["countdown_seconds"] or 60)
    if item.get("round_id") is not None and item.get("status") == "COUNTDOWN":
        item["countdown_remaining"] = int(get_remaining_bingo_countdown(int(item["round_id"])))
    else:
        item["countdown_remaining"] = 0
    item["commission_percent"] = round(float(item["commission_percent"] or 0), 2)
    item["total_pot"] = round(float(item["total_pot"] or 0), 2)
    item["commission_amount"] = round(float(item["commission_amount"] or 0), 2)
    item["prize_pool"] = round(float(item["prize_pool"] or 0), 2)
    item["called_count"] = int(item["called_count"] or 0)
    item["winner_count"] = int(item["winner_count"] or 0)
    if item.get("round_id") is not None:
        item["round_id"] = int(item["round_id"])
    return item


def ensure_round_for_room(room_id):
    current = None
    for row in get_bingo_dashboard_data():
        if int(row["room_id"]) == int(room_id):
            current = row
            break
    if current and current["round_id"]:
        return get_bingo_round(int(current["round_id"]))
    created, status = create_bingo_round(int(room_id))
    if not created:
        return None
    return created


def progress_round(round_id):
    """Advance a round when the browser polls it.

    WAITING -> COUNTDOWN is normally done by join_bingo_round.
    COUNTDOWN -> PLAYING is handled by the database countdown timer.
    PLAYING draws at most one number per poll and checks for winners.
    WINNER -> RESULT -> FINISHED is handled on subsequent polls.
    """
    with engine_lock:
        row = get_bingo_round(round_id)
        if not row:
            return None

        status = row["status"]
        if status == "COUNTDOWN":
            updated, result = start_bingo_playing(round_id)
            if result == "playing":
                row = updated
                status = "PLAYING"
            else:
                row = get_bingo_round(round_id)
                status = row["status"] if row else status

        if status == "PLAYING":
            row = get_bingo_round(round_id)
            if not row:
                return None
            called_count = int(row["called_count"] or 0)
            playing_started = row["playing_started_at"]

            should_call = False
            if called_count == 0:
                should_call = True
            elif playing_started:
                # SQLite stores UTC timestamps. The database itself uses the
                # same clock, so this calculation is only a lightweight gate.
                import sqlite3
                from database import get_connection
                connection = get_connection()
                try:
                    elapsed = connection.execute(
                        "SELECT (julianday('now') - julianday(?)) * 86400.0 AS seconds_elapsed",
                        (playing_started,),
                    ).fetchone()["seconds_elapsed"]
                finally:
                    connection.close()
                should_call = float(elapsed or 0) >= (called_count * CALL_INTERVAL_SECONDS)

            if should_call and called_count < 75:
                call_next_bingo_number(round_id)

                winners, winner_status = find_bingo_winners(round_id)
                if winner_status == "ok" and winners:
                    finish_bingo_round_with_winners(round_id)

        elif status == "WINNER":
            # Keep the winner state long enough for every spectator to see the
            # winning cartel, pattern and prize. The browser closes the popup
            # after this same period, but the server is authoritative.
            import sqlite3
            from database import get_connection
            connection = get_connection()
            try:
                expiry = connection.execute(
                    "SELECT winner_expires_at FROM bingo_rounds WHERE id = ?", (round_id,)
                ).fetchone()["winner_expires_at"]
                expired = bool(connection.execute(
                    "SELECT datetime('now') >= datetime(?) AS expired", (expiry,)
                ).fetchone()["expired"]) if expiry else True
            finally:
                connection.close()
            if expired:
                set_bingo_round_result(round_id)
                finish_bingo_round(round_id)
        elif status == "RESULT":
            finish_bingo_round(round_id)

        return get_bingo_round(round_id)



# ============================================================
# ADMIN MINI APP API
# ============================================================

def require_admin(init_data: str | None, grant: str | None = None):
    account, telegram_user = auth_from_header(init_data)
    telegram_id = int(telegram_user["id"])

    if not is_admin_user(telegram_id):
        # SUPER_ADMIN_ID is also accepted as an administrator.
        try:
            if int(telegram_id) != int(os.getenv("SUPER_ADMIN_ID", "0")):
                raise HTTPException(status_code=403, detail="Administrator access required")
        except ValueError:
            raise HTTPException(status_code=403, detail="Administrator access required")

    if grant and telegram_id != int(os.getenv("SUPER_ADMIN_ID", "0") or 0):
        if not has_admin_grant(telegram_id, grant):
            raise HTTPException(status_code=403, detail=f"Administrator permission required: {grant}")

    return account, telegram_user


@app.get("/api/admin")
def admin_info(x_telegram_init_data: str | None = Header(default=None)):
    account, telegram_user = require_admin(x_telegram_init_data)
    telegram_id = int(telegram_user["id"])
    super_admin = telegram_id == int(os.getenv("SUPER_ADMIN_ID", "0") or 0)

    return {
        "success": True,
        "is_admin": True,
        "is_super_admin": super_admin,
        "grants": list(get_admin_grants(telegram_id)),
        "user": user_payload(account),
        "commission_percent": get_bingo_commission_percent(),
    }


@app.get("/api/admin/dashboard")
def admin_dashboard_api(x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "dashboard")
    stats = get_admin_statistics()
    return {"success": True, "statistics": stats}


@app.get("/api/admin/bingo-games")
def admin_bingo_games_api(x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "bingo_rooms")
    rooms = [row_to_dict(r) for r in get_bingo_rooms(active_only=False)]
    return {"success": True, "rooms": rooms}


@app.get("/api/admin/deposits")
def admin_deposits_api(x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "deposits")
    return {"success": True, "deposits": [row_to_dict(r) for r in get_pending_deposits()]}


@app.get("/api/admin/withdrawals")
def admin_withdrawals_api(x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "withdrawals")
    return {"success": True, "withdrawals": [row_to_dict(r) for r in get_pending_withdrawals()]}


@app.post("/api/admin/deposits/{request_id}/approve")
def admin_approve_deposit(request_id: int, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "deposits")
    player, status, approved_amount = approve_deposit(request_id)
    if status != "approved":
        raise HTTPException(status_code=409, detail=status)
    return {
        "success": True,
        "message": "Deposit approved",
        "amount": float(approved_amount or 0),
        "player": user_payload(player),
    }


@app.post("/api/admin/deposits/{request_id}/reject")
def admin_reject_deposit(request_id: int, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "deposits")
    player, status = reject_deposit(request_id)
    if status != "rejected":
        raise HTTPException(status_code=409, detail=status)
    return {"success": True, "message": "Deposit rejected"}


@app.post("/api/admin/withdrawals/{request_id}/approve")
def admin_approve_withdrawal(request_id: int, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "withdrawals")
    player, status, approved_amount = approve_withdrawal(request_id)
    if status != "approved":
        raise HTTPException(status_code=409, detail=status)
    return {
        "success": True,
        "message": "Withdrawal approved",
        "amount": float(approved_amount or 0),
    }


@app.post("/api/admin/withdrawals/{request_id}/reject")
def admin_reject_withdrawal(request_id: int, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "withdrawals")
    player, status = reject_withdrawal(request_id)
    if status != "rejected":
        raise HTTPException(status_code=409, detail=status)
    return {"success": True, "message": "Withdrawal rejected"}


@app.get("/api/admin/settings")
def admin_settings_api(x_telegram_init_data: str | None = Header(default=None)):
    account, telegram_user = require_admin(x_telegram_init_data)
    patterns = [row_to_dict(r) for r in get_all_bingo_patterns()]
    return {
        "success": True,
        "commission_percent": get_bingo_commission_percent(),
        "registration_bonus": get_system_setting_float("registration_bonus", 0),
        "referral_bonus": get_system_setting_float("referral_bonus", 0),
        "first_deposit_required": get_system_setting_float("first_deposit_required", 200),
        "min_withdrawal": get_system_setting_float("min_withdrawal", 100),
        "max_withdrawal": get_system_setting_float("max_withdrawal", 10000),
        "patterns": patterns,
    }


class GeneralSettingsRequest(BaseModel):
    registration_bonus: float
    referral_bonus: float
    first_deposit_required: float
    min_withdrawal: float
    max_withdrawal: float


@app.post("/api/admin/settings/general")
def admin_set_general_settings(
    body: GeneralSettingsRequest,
    x_telegram_init_data: str | None = Header(default=None),
):
    require_admin(x_telegram_init_data, "settings")
    if min(body.registration_bonus, body.referral_bonus, body.first_deposit_required, body.min_withdrawal, body.max_withdrawal) < 0:
        raise HTTPException(status_code=400, detail="Settings cannot be negative")
    if body.max_withdrawal and body.max_withdrawal < body.min_withdrawal:
        raise HTTPException(status_code=400, detail="Maximum withdrawal cannot be below minimum")
    for key, value in {
        "registration_bonus": body.registration_bonus,
        "referral_bonus": body.referral_bonus,
        "first_deposit_required": body.first_deposit_required,
        "min_withdrawal": body.min_withdrawal,
        "max_withdrawal": body.max_withdrawal,
    }.items():
        set_system_setting(key, value)
    return {"success": True, "message": "General settings saved"}


class CommissionRequest(BaseModel):
    percent: float


@app.post("/api/admin/settings/commission")
def admin_set_commission(
    body: CommissionRequest,
    x_telegram_init_data: str | None = Header(default=None),
):
    require_admin(x_telegram_init_data, "commission")
    ok, status = set_bingo_commission_percent(body.percent)
    if not ok:
        raise HTTPException(status_code=400, detail=status)
    return {
        "success": True,
        "commission_percent": get_bingo_commission_percent(),
    }


class PatternRequest(BaseModel):
    enabled: bool


@app.post("/api/admin/settings/patterns/{pattern_key}")
def admin_set_pattern(
    pattern_key: str,
    body: PatternRequest,
    x_telegram_init_data: str | None = Header(default=None),
):
    require_admin(x_telegram_init_data, "bingo_settings")
    ok = set_bingo_pattern_enabled(pattern_key, body.enabled)
    if not ok:
        raise HTTPException(status_code=400, detail="Pattern not found")
    return {"success": True, "pattern_key": pattern_key.upper(), "enabled": body.enabled}


class PlayerAdjustmentRequest(BaseModel):
    telegram_user_id: int
    amount: float


@app.post("/api/admin/player/bonus")
def admin_adjust_bonus(body: PlayerAdjustmentRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "player_bonus")
    player, status = adjust_demo_bonus_balance(body.telegram_user_id, body.amount)
    if status != "adjusted":
        raise HTTPException(status_code=404, detail=status)
    return {"success": True, "user": user_payload(player)}


@app.post("/api/admin/player/main")
def admin_adjust_main(body: PlayerAdjustmentRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "player_balance")
    player, status = adjust_demo_main_balance(body.telegram_user_id, body.amount)
    if status != "adjusted":
        raise HTTPException(status_code=404, detail=status)
    return {"success": True, "user": user_payload(player)}


@app.post("/api/admin/player/withdrawable")
def admin_adjust_withdrawable(body: PlayerAdjustmentRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "player_balance")
    player, status = adjust_demo_withdrawable_balance(body.telegram_user_id, body.amount)
    if status != "adjusted":
        raise HTTPException(status_code=404, detail=status)
    return {"success": True, "user": user_payload(player)}


class BingoRoomRequest(BaseModel):
    bet_amount: float
    max_cards: int


class BingoRoomUpdateRequest(BaseModel):
    bet_amount: float | None = None
    max_cards: int | None = None
    is_active: bool | None = None


@app.post("/api/admin/bingo-games")
def admin_create_bingo_game(body: BingoRoomRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "bingo_rooms")
    room, status = create_bingo_room(body.bet_amount, body.max_cards)
    if status != "created":
        raise HTTPException(status_code=409, detail=status)
    return {"success": True, "room": row_to_dict(room)}


@app.patch("/api/admin/bingo-games/{room_id}")
def admin_update_bingo_game(room_id: int, body: BingoRoomUpdateRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "bingo_rooms")
    room, status = update_bingo_room(room_id, body.bet_amount, body.max_cards, body.is_active)
    if status not in ("updated",):
        raise HTTPException(status_code=409, detail=status)
    return {"success": True, "room": row_to_dict(room)}


class AdminCreateRequest(BaseModel):
    telegram_user_id: int
    grants: list[str] = []


class AdminGrantRequest(BaseModel):
    grants: list[str]


class AdminActiveRequest(BaseModel):
    active: bool


@app.post("/api/admin/admins")
def admin_create_admin(body: AdminCreateRequest, x_telegram_init_data: str | None = Header(default=None)):
    _, telegram_user = require_admin(x_telegram_init_data, "manage_admins")
    admin, status = create_admin_user(body.telegram_user_id, body.grants, int(telegram_user["id"]))
    if status != "created":
        raise HTTPException(status_code=409, detail=status)
    return {"success": True, "admin": row_to_dict(admin)}


@app.patch("/api/admin/admins/{telegram_user_id}/grants")
def admin_update_grants(telegram_user_id: int, body: AdminGrantRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "manage_admins")
    if any(g not in ADMIN_GRANTS for g in body.grants):
        raise HTTPException(status_code=400, detail="Invalid administrator permission")
    admin, status = set_admin_grants(telegram_user_id, body.grants)
    if status != "updated":
        raise HTTPException(status_code=404, detail=status)
    return {"success": True, "admin": row_to_dict(admin)}


@app.patch("/api/admin/admins/{telegram_user_id}/active")
def admin_update_active(telegram_user_id: int, body: AdminActiveRequest, x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "manage_admins")
    if not set_admin_active(telegram_user_id, body.active):
        raise HTTPException(status_code=404, detail="Administrator not found")
    return {"success": True, "active": body.active}


@app.get("/api/admin/admins")
def admin_list_admins_api(x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "manage_admins")
    return {"success": True, "admins": get_all_admins()}


@app.get("/api/admin/activity")
def admin_activity_api(x_telegram_init_data: str | None = Header(default=None)):
    require_admin(x_telegram_init_data, "dashboard")
    return {"success": True, "activity": get_admin_activity(100)}


@app.on_event("startup")
def startup():
    init_database()


@app.get("/")
def root():
    return {
        "success": True,
        "message": "Bingo Mini App backend is running.",
    }


@app.get("/health")
def health():
    return {"success": True, "status": "ok"}


@app.get("/api/me")
def me(x_telegram_init_data: str | None = Header(default=None)):
    account, telegram_user = auth_from_header(x_telegram_init_data)
    telegram_id = int(telegram_user["id"])
    try:
        super_admin = telegram_id == int(os.getenv("SUPER_ADMIN_ID", "0") or 0)
    except Exception:
        super_admin = False

    return {
        "success": True,
        "user": user_payload(account),
        "telegram": {
            "id": telegram_id,
            "username": telegram_user.get("username"),
            "first_name": telegram_user.get("first_name"),
            "last_name": telegram_user.get("last_name"),
        },
        "is_admin": bool(super_admin or is_admin_user(telegram_id)),
        "is_super_admin": super_admin,
        "admin_grants": list(get_admin_grants(telegram_id)),
    }


# ============================================================
# PLAYER MINI APP API
# ============================================================

@app.get("/api/profile")
def profile_api(x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    profile = get_user_profile(int(account["telegram_user_id"]))
    return {"success": True, "profile": row_to_dict(profile), "user": user_payload(account)}


@app.get("/api/wallet/banks")
def wallet_banks(x_telegram_init_data: str | None = Header(default=None)):
    auth_from_header(x_telegram_init_data)
    return {"success": True, "banks": [row_to_dict(r) for r in get_demo_banks()]}


@app.get("/api/deposits")
def my_deposits(x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    return {"success": True, "deposits": [row_to_dict(r) for r in get_user_deposit_requests(int(account["telegram_user_id"]))]}


@app.post("/api/deposits")
def create_deposit(body: DepositRequestBody, x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    request_id, status = create_deposit_request(
        int(account["telegram_user_id"]), body.bank_id, body.amount, body.transaction_id
    )
    if status != "created":
        messages = {
            "invalid_amount": "Enter a valid deposit amount",
            "invalid_transaction_id": "Enter a valid demo transaction/reference ID",
            "bank_not_found": "Selected demo bank was not found",
            "pending_same_bank": "You already have a pending deposit for this bank",
            "user_not_found": "Player account not found",
        }
        raise HTTPException(status_code=409, detail=messages.get(status, status))
    return {"success": True, "request_id": request_id, "message": "Deposit request submitted"}


@app.get("/api/withdrawals")
def my_withdrawals(x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    return {"success": True, "withdrawals": [row_to_dict(r) for r in get_user_withdrawal_requests(int(account["telegram_user_id"]))]}


@app.post("/api/withdrawals")
def create_withdrawal(body: WithdrawalRequestBody, x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    request_id, status = create_withdrawal_request(
        int(account["telegram_user_id"]), body.bank_id, body.amount,
        body.account_number.strip(), body.account_name.strip()
    )
    if status != "created":
        messages = {
            "invalid_amount": "Enter a valid withdrawal amount",
            "bank_not_found": "Selected demo bank was not found",
            "first_deposit_required": "First approved deposit requirement has not been met",
            "below_minimum": "Withdrawal amount is below the minimum",
            "above_maximum": "Withdrawal amount is above the maximum",
            "insufficient_balance": "Insufficient withdrawable balance",
            "pending_exists": "You already have a pending withdrawal",
            "user_not_found": "Player account not found",
        }
        raise HTTPException(status_code=409, detail=messages.get(status, status))
    return {"success": True, "request_id": request_id, "message": "Withdrawal request submitted"}


def _telegram_api(method, fields=None, file_field=None, file_bytes=None, file_name=None, content_type=None):
    """Small standard-library Telegram Bot API helper used by Mini App broadcasts."""
    import urllib.request
    import uuid
    boundary = "----BingoBoundary" + uuid.uuid4().hex
    body = bytearray()
    fields = fields or {}
    for key, value in fields.items():
        body.extend((f"--{boundary}\r\n").encode())
        body.extend((f'Content-Disposition: form-data; name="{key}"\r\n\r\n').encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")
    if file_field and file_bytes is not None:
        body.extend((f"--{boundary}\r\n").encode())
        body.extend((f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name or "upload"}"\r\n').encode())
        body.extend((f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n").encode())
        body.extend(file_bytes)
        body.extend(b"\r\n")
    body.extend((f"--{boundary}--\r\n").encode())
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=bytes(body), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


@app.post("/api/admin/broadcast")
async def admin_broadcast(
    text: str = Form(""),
    media_type: str = Form("text"),
    media: UploadFile | None = File(default=None),
    x_telegram_init_data: str | None = Header(default=None),
):
    require_admin(x_telegram_init_data, "dashboard")
    text = (text or "").strip()
    media_type = (media_type or "text").lower()
    if not text and media is None:
        raise HTTPException(status_code=400, detail="Enter a message or choose a media file")
    allowed = {"text", "photo", "gif", "video"}
    if media_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported broadcast type")
    file_bytes = await media.read() if media is not None else None
    player_ids = get_all_player_telegram_ids()
    sent = 0
    failed = 0
    reusable_file_id = None
    for chat_id in player_ids:
        if media is None:
            result = _telegram_api("sendMessage", {"chat_id": chat_id, "text": text})
        else:
            method = {"photo":"sendPhoto", "gif":"sendAnimation", "video":"sendVideo"}[media_type]
            field = {"photo":"photo", "gif":"animation", "video":"video"}[media_type]
            if reusable_file_id:
                result = _telegram_api(method, {"chat_id": chat_id, field: reusable_file_id, **({"caption": text} if text else {})})
            else:
                result = _telegram_api(method, {"chat_id": chat_id, **({"caption": text} if text else {})}, field, file_bytes, media.filename, media.content_type)
                if result.get("ok"):
                    obj = result.get("result") or {}
                    item = obj.get("photo", [])[-1] if field == "photo" and obj.get("photo") else obj.get(field)
                    reusable_file_id = item.get("file_id") if isinstance(item, dict) else None
        if result.get("ok"):
            sent += 1
        else:
            failed += 1
    return {"success": True, "sent": sent, "failed": failed, "total": len(player_ids)}


@app.get("/api/admin/database-backup")
def admin_database_backup(x_telegram_init_data: str | None = Header(default=None), init_data: str | None = None):
    require_admin(x_telegram_init_data or init_data, "dashboard")
    if not DATABASE_FILE.exists():
        raise HTTPException(status_code=404, detail="Database file not found")
    return FileResponse(str(DATABASE_FILE), media_type="application/x-sqlite3", filename="bingo-backup.db")


@app.get("/api/bingo/dashboard")
def bingo_dashboard(x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    rooms = []
    for raw in get_bingo_dashboard_data():
        room = room_payload(raw)
        if not room["round_id"]:
            round_row = create_bingo_round(room["room_id"])[0]
            if round_row:
                room["round_id"] = int(round_row["id"])
                room["round_number"] = int(round_row["round_number"])
                room["status"] = round_row["status"]
        rooms.append(room)

    return {
        "success": True,
        "user": user_payload(account),
        "rooms": rooms,
    }


@app.get("/api/bingo/rooms/{room_id}")
def bingo_room(room_id: int, x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    round_row = ensure_round_for_room(room_id)
    if not round_row:
        raise HTTPException(status_code=404, detail="Bingo room not found")
    round_row = progress_round(int(round_row["id"]))
    if not round_row:
        raise HTTPException(status_code=404, detail="Bingo round not found")
    if round_row["status"] == "FINISHED":
        created, _ = create_bingo_round(room_id)
        if created:
            round_row = created

    room_row = __import__("database").get_bingo_room(room_id)
    players = [row_to_dict(r) for r in get_bingo_round_players(round_row["id"])]

    # IMPORTANT:
    # The card-selection page must show ONLY cartel/card numbers.
    # The actual 5x5 card data is returned by /my-cards after the player joins.
    available_cards = [
        {
            "id": int(c["id"]),
            "card_number": int(c["card_number"]),
        }
        for c in get_available_bingo_cards(round_row["id"])
    ]

    my_cards = []
    for p in players:
        if int(p.get("user_id") or 0) != int(account["id"]):
            continue
        item = dict(p)
        try:
            item["card_data"] = json.loads(item.get("card_data")) if isinstance(item.get("card_data"), str) else item.get("card_data")
        except Exception:
            item["card_data"] = []
        item["id"] = int(item["card_id"])
        item["card_number"] = int(item["card_number"])
        my_cards.append({"id": item["id"], "card_number": item["card_number"], "card_data": item["card_data"]})

    remaining = get_remaining_bingo_countdown(int(round_row["id"])) if round_row["status"] == "COUNTDOWN" else 0

    return {
        "success": True,
        "user": user_payload(account),
        "room": row_to_dict(room_row),
        "round": row_to_dict(round_row),
        "players": players,
        "my_cards": my_cards,
        "available_cards": available_cards,
        "countdown_remaining": int(remaining),
    }



@app.get("/api/bingo/rounds/{round_id}/my-cards")
def bingo_my_cards(round_id: int, x_telegram_init_data: str | None = Header(default=None)):
    """Return the authenticated player's full cartels for the actual game screen."""
    account, _ = auth_from_header(x_telegram_init_data)
    players = get_bingo_round_players(round_id, active_only=False)

    cards = []
    for player in players:
        item = row_to_dict(player)
        if int(item.get("user_id") or 0) != int(account["id"]):
            continue
        raw = item.get("card_data")
        try:
            item["card_data"] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            item["card_data"] = []
        item["card_id"] = int(item["card_id"])
        item["card_number"] = int(item["card_number"])
        cards.append(item)

    return {
        "success": True,
        "round_id": int(round_id),
        "cards": cards,
    }


@app.post("/api/bingo/rooms/{room_id}/join")
def bingo_join(
    room_id: int,
    body: JoinRequest,
    x_telegram_init_data: str | None = Header(default=None),
):
    account, _ = auth_from_header(x_telegram_init_data)
    round_row = ensure_round_for_room(room_id)
    if not round_row:
        raise HTTPException(status_code=404, detail="Bingo room not found")

    player, status = join_bingo_round(
        int(round_row["id"]),
        int(account["telegram_user_id"]),
        int(body.card_id),
    )
    if status != "joined":
        messages = {
            "user_not_found": "Player account not found",
            "round_not_found": "Round not found",
            "round_started": "This game has already started. You can watch until it ends.",
            "room_full": "This room is full",
            "cards_full": "All cards in this room are already selected",
            "card_not_found": "That card does not exist",
            "card_taken": "That card has just been taken by another player",
            "already_joined_card": "You already selected this card",
            "insufficient_balance": "Insufficient demo balance for this bet",
        }
        raise HTTPException(status_code=409, detail=messages.get(status, status))

    return {
        "success": True,
        "message": "Card selected successfully",
        "player": row_to_dict(player),
        "round": row_to_dict(get_bingo_round(round_row["id"])),
    }


@app.get("/api/bingo/rounds/{round_id}/state")
def bingo_round_state(round_id: int, x_telegram_init_data: str | None = Header(default=None)):
    account, _ = auth_from_header(x_telegram_init_data)
    row = progress_round(round_id)
    if not row:
        raise HTTPException(status_code=404, detail="Round not found")

    called = [int(r["number"]) for r in get_bingo_calls(round_id)]
    players = get_bingo_round_players(round_id, active_only=False)
    summary = calculate_bingo_round_financials(round_id) or {}
    remaining = get_remaining_bingo_countdown(round_id) if row["status"] == "COUNTDOWN" else 0
    patterns = [row_to_dict(p) for p in get_enabled_bingo_patterns()]
    winners = get_bingo_winners(round_id) if row["status"] in ("WINNER", "RESULT", "FINISHED") else []
    for winner in winners:
        try:
            winner["card_data"] = json.loads(winner["card_data"]) if isinstance(winner.get("card_data"), str) else winner.get("card_data")
        except Exception:
            winner["card_data"] = []

    return {
        "success": True,
        "user": user_payload(account),
        "round": row_to_dict(row),
        "status": row["status"],
        "countdown_remaining": int(remaining),
        "called_numbers": called,
        "last_called": called[-1] if called else None,
        "players": [row_to_dict(p) for p in players],
        "financials": summary,
        "patterns": patterns,
        "winners": winners,
    }
