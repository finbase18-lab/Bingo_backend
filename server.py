import hashlib
import hmac
import json
import os
import time
from threading import Lock
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from config import BOT_TOKEN
except Exception:
    BOT_TOKEN = ""

if not BOT_TOKEN:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    
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
            set_bingo_round_result(round_id)
        elif status == "RESULT":
            finish_bingo_round(round_id)

        return get_bingo_round(round_id)


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
    return {
        "success": True,
        "user": user_payload(account),
        "telegram": {
            "id": int(telegram_user["id"]),
            "username": telegram_user.get("username"),
            "first_name": telegram_user.get("first_name"),
            "last_name": telegram_user.get("last_name"),
        },
    }


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

    room_row = __import__("database").get_bingo_room(room_id)
    players = [row_to_dict(r) for r in get_bingo_round_players(round_row["id"])]
    available_cards = [row_to_dict(c) for c in get_available_bingo_cards(round_row["id"])]
    my_cards = [p for p in players if int(p.get("user_id") or 0) == int(account["id"])]

    return {
        "success": True,
        "user": user_payload(account),
        "room": row_to_dict(room_row),
        "round": row_to_dict(round_row),
        "players": players,
        "my_cards": my_cards,
        "available_cards": available_cards,
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
    }
