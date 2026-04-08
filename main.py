import hashlib
import secrets
import random
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

app = FastAPI()

# ========== ХРАНЕНИЕ В ПАМЯТИ ==========
users = {}          # token -> {"nick": str, "pass_hash": str}
email_to_token = {}
temp_codes = {}     # email -> {"code": str, "expires": datetime}
active_ws = {}
messages = []       # {"from": nick, "to": nick, "text": str, "time": str}

def hash_pwd(p):
    return hashlib.sha256(p.encode()).hexdigest()

def gen_token():
    return secrets.token_urlsafe(32)

@app.post("/send_code")
async def send_code(email: str = Form(...)):
    code = str(random.randint(100000, 999999))
    temp_codes[email] = {"code": code, "expires": datetime.utcnow() + timedelta(minutes=10)}
    # Код выводится в лог Render — найди его там
    print(f"===== КОД ДЛЯ {email}: {code} =====")
    return {"ok": True}

@app.post("/register")
async def register(email: str = Form(...), nick: str = Form(...), password: str = Form(...), code: str = Form(...)):
    if email not in temp_codes or temp_codes[email]["expires"] < datetime.utcnow() or temp_codes[email]["code"] != code:
        raise HTTPException(400, "Неверный или просроченный код")
    if email in email_to_token:
        raise HTTPException(400, "Email уже занят")
    token = gen_token()
    users[token] = {"nick": nick, "pass_hash": hash_pwd(password)}
    email_to_token[email] = token
    del temp_codes[email]
    return {"token": token, "nick": nick}

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    if email not in email_to_token:
        raise HTTPException(400, "Email не найден")
    token = email_to_token[email]
    if users[token]["pass_hash"] != hash_pwd(password):
        raise HTTPException(400, "Неверный пароль")
    return {"token": token, "nick": users[token]["nick"]}

@app.websocket("/ws/{token}")
async def ws_endpoint(websocket: WebSocket, token: str):
    if token not in users:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    active_ws[token] = websocket
    nick = users[token]["nick"]
    # Отправить историю
    for msg in messages[-30:]:
        if msg["to"] == nick or msg["from"] == nick:
            await websocket.send_json(msg)
    try:
        while True:
            data = await websocket.receive_json()
            to_nick = data.get("to")
            text = data.get("text", "")[:500]
            if not to_nick or not text:
                continue
            msg_obj = {"from": nick, "text": text, "time": datetime.now().strftime("%H:%M"), "to": to_nick}
            messages.append(msg_obj)
            # найти токен получателя
            target_token = None
            for t, u in users.items():
                if u["nick"] == to_nick:
                    target_token = t
                    break
            if target_token and target_token in active_ws:
                await active_ws[target_token].send_json(msg_obj)
            await websocket.send_json(msg_obj)
    except WebSocketDisconnect:
        del active_ws[token]

app.mount("/", StaticFiles(directory="static", html=True), name="static")
