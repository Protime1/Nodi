from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
import hashlib
import secrets
import random
from datetime import datetime, timedelta
import os
import httpx
import smtplib
from email.mime.text import MIMEText
from jose import jwt
import cloudinary
import cloudinary.uploader
import uuid
from threading import Thread
import time

app = FastAPI()

# ==================================================
# 🔴🔴🔴 ЗАМЕНИ ЭТИ 8 СТРОЧЕК ПОТОМ 🔴🔴🔴
# ==================================================
SECRET_KEY = "chat_code_school_2026RKN_nodi_py_html_txt30.03.2013"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1491323092591448145/4foK_mrpgnAYjTaOdAZsP0ItQ0tuhvs0NTYyQbxdYFdeIs5X_UafNQwIeG96snEfAxrL"
YANDEX_EMAIL = "peter.klenyaev@yandex.ru"
YANDEX_PASSWORD = "pqzlqhzxeizljlwx"
CLOUDINARY_CLOUD_NAME = "dn7bela6z"
CLOUDINARY_API_KEY = "955743566196878"
CLOUDINARY_API_SECRET = "M0CLWZb4J7L4J2ikTK-Q3tdkRA4"
# ==================================================

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

def create_token(email: str):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": email, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except:
        return None

users = {}
emails = {}
temp_codes = {}
messages = []
channels = {}
active_connections = {}
secure_links = {}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return secrets.token_urlsafe(32)

def get_client_ip(request: Request):
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def send_yandex_email(to_email: str, code: str):
    try:
        msg = MIMEText(f"Ваш код подтверждения для Nodi: {code}\n\nКод действителен 15 минут.", "plain", "utf-8")
        msg["Subject"] = "Код подтверждения Nodi"
        msg["From"] = YANDEX_EMAIL
        msg["To"] = to_email
        with smtplib.SMTP_SSL("smtp.yandex.ru", 465) as server:
            server.login(YANDEX_EMAIL, YANDEX_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

async def send_discord_message(title: str, description: str, color: int = 0x00aaff, fields: list = None):
    if not DISCORD_WEBHOOK_URL:
        return
    embed = {"title": title, "description": description, "color": color, "timestamp": datetime.utcnow().isoformat()}
    if fields:
        embed["fields"] = fields
    try:
        async with httpx.AsyncClient() as client:
            await client.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=3)
    except:
        pass

async def send_online_count():
    count = len(active_connections)
    await send_discord_message(title="📊 Онлайн статистика", description=f"Сейчас в Nodi: **{count}** человек", color=0x88ff88 if count > 0 else 0xffaa00)

@app.post("/send_code")
async def send_code(request: Request, email: str = Form(...)):
    code = str(random.randint(100000, 999999))
    expires = datetime.utcnow() + timedelta(minutes=15)
    temp_codes[email] = {"code": code, "expires": expires}
    if send_yandex_email(email, code):
        client_ip = get_client_ip(request)
        await send_discord_message(title="📧 Код подтверждения отправлен", description=f"Код отправлен на **{email}**", color=0xffaa00, fields=[{"name": "🌐 IP", "value": f"`{client_ip}`", "inline": True}])
        return {"status": "sent"}
    else:
        raise HTTPException(status_code=500, detail="Не удалось отправить письмо")

@app.post("/register")
async def register(request: Request, email: str = Form(...), nickname: str = Form(...), password: str = Form(...), code: str = Form(...)):
    if email not in temp_codes:
        raise HTTPException(status_code=400, detail="Сначала запросите код")
    code_data = temp_codes[email]
    if code_data["expires"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Код истёк")
    if code_data["code"] != code:
        raise HTTPException(status_code=400, detail="Неверный код")
    if email in emails:
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    if len(nickname) < 2:
        raise HTTPException(status_code=400, detail="Ник слишком короткий")
    token = generate_token()
    client_ip = get_client_ip(request)
    jwt_token = create_token(email)
    users[token] = {"email": email, "nickname": nickname, "ip": client_ip}
    emails[email] = {"nickname": nickname, "password_hash": hash_password(password)}
    del temp_codes[email]
    await send_discord_message(title="📝 Новая регистрация", description=f"**{nickname}** зарегистрировался в Nodi", color=0x00ff00, fields=[{"name": "📧 Email", "value": email, "inline": True}, {"name": "🌐 IP", "value": f"`{client_ip}`", "inline": True}])
    return {"token": token, "jwt_token": jwt_token, "nickname": nickname, "email": email}

@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    if email not in emails:
        raise HTTPException(status_code=400, detail="Email не найден")
    if emails[email]["password_hash"] != hash_password(password):
        client_ip = get_client_ip(request)
        await send_discord_message(title="⚠️ Неудачная попытка входа", description=f"Попытка входа в **{email}**", color=0xff0000, fields=[{"name": "🌐 IP", "value": f"`{client_ip}`", "inline": True}])
        raise HTTPException(status_code=400, detail="Неверный пароль")
    token = None
    for t, u in users.items():
        if u["email"] == email:
            token = t
            break
    if not token:
        raise HTTPException(status_code=400, detail="Ошибка")
    client_ip = get_client_ip(request)
    nickname = users[token]["nickname"]
    users[token]["ip"] = client_ip
    jwt_token = create_token(email)
    await send_discord_message(title="✅ Успешный вход", description=f"**{nickname}** вошёл в Nodi", color=0x00aaff, fields=[{"name": "📧 Email", "value": email, "inline": True}, {"name": "🌐 IP", "value": f"`{client_ip}`", "inline": True}])
    return {"token": token, "jwt_token": jwt_token, "nickname": nickname, "email": email}

@app.post("/upload_media")
async def upload_media(file: UploadFile = File(...), token: str = Form(...), channel_slug: str = Form(default="")):
    if token not in users:
        raise HTTPException(status_code=401, detail="Не авторизован")
    try:
        upload_result = cloudinary.uploader.upload(file.file, folder="nodi_messenger", resource_type="auto", quality="auto:good", fetch_format="auto", flags="progressive")
        cloudinary_url = cloudinary.CloudinaryImage(upload_result["public_id"]).build_url(quality="auto:good", fetch_format="auto")
        link_id = str(uuid.uuid4()).replace("-", "")[:16]
        secure_links[link_id] = {"cloudinary_url": cloudinary_url, "channel_slug": channel_slug, "expires": datetime.now() + timedelta(minutes=30), "views": 0}
        private_url = f"/share/{link_id}"
        return {"url": private_url, "type": "image" if upload_result["resource_type"] == "image" else "video", "filename": file.filename, "public_id": upload_result["public_id"], "expires_in": 1800}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки: {str(e)}")

@app.get("/share/{link_id}")
async def get_private_file(link_id: str, token: str = None):
    if not token or token not in users:
        raise HTTPException(status_code=401, detail="🔒 Нужно войти в аккаунт")
    if link_id not in secure_links:
        raise HTTPException(status_code=404, detail="❌ Ссылка не найдена")
    link_data = secure_links[link_id]
    if link_data["expires"] < datetime.now():
        del secure_links[link_id]
        raise HTTPException(status_code=410, detail="⏰ Ссылка истекла")
    channel_slug = link_data["channel_slug"]
    if channel_slug and channel_slug in channels:
        if token not in channels[channel_slug]["members"]:
            raise HTTPException(status_code=403, detail="🚫 Нет доступа к этому файлу")
    link_data["views"] += 1
    return RedirectResponse(link_data["cloudinary_url"], headers={"Cache-Control": "public, max-age=2592000, immutable", "CDN-Cache-Control": "public, max-age=2592000", "X-View-Count": str(link_data["views"])})

@app.post("/create_channel")
async def create_channel(slug: str = Form(...), name: str = Form(...), token: str = Form(...), write_permission: str = Form("all")):
    if token not in users:
        raise HTTPException(status_code=401, detail="Не авторизован")
    if slug in channels:
        raise HTTPException(status_code=400, detail="Канал уже есть")
    channels[slug] = {"name": name, "owner_token": token, "admins": [token], "members": [token], "write_permission": write_permission}
    await send_discord_message(title="📢 Новый канал", description=f"**{users[token]['nickname']}** создал канал **{name}**", color=0x00aaff, fields=[{"name": "🔗 Slug", "value": slug, "inline": True}])
    return {"slug": slug, "invite_link": f"/?join={slug}"}

@app.post("/join_channel")
async def join_channel(slug: str = Form(...), token: str = Form(...)):
    if token not in users:
        raise HTTPException(status_code=401, detail="Не авторизован")
    if slug not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")
    if token not in channels[slug]["members"]:
        channels[slug]["members"].append(token)
        await send_discord_message(title="👋 Новый участник", description=f"**{users[token]['nickname']}** вступил в канал **{channels[slug]['name']}**", color=0x88ff88)
    return {"status": "joined"}

@app.post("/get_channel_members")
async def get_channel_members(slug: str = Form(...), token: str = Form(...)):
    if token not in users:
        raise HTTPException(status_code=401, detail="Не авторизован")
    if slug not in channels:
        raise HTTPException(status_code=404, detail="Канал не найден")
    channel = channels[slug]
    members_list = [{"token": mt, "nickname": users[mt]["nickname"], "email": users[mt]["email"]} for mt in channel["members"]]
    return {"members": members_list, "admins": channel["admins"], "owner_token": channel["owner_token"], "is_admin": token in channel["admins"], "is_owner": token == channel["owner_token"], "write_permission": channel["write_permission"]}

@app.post("/make_admin")
async def make_admin(channel_slug: str = Form(...), user_nickname: str = Form(...), token: str = Form(...)):
    if token not in users or channel_slug not in channels or token not in channels[channel_slug]["admins"]:
        raise HTTPException(status_code=403, detail="Нет прав")
    target_token = next((t for t, u in users.items() if u["nickname"] == user_nickname), None)
    if not target_token or target_token not in channels[channel_slug]["members"]:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if target_token not in channels[channel_slug]["admins"]:
        channels[channel_slug]["admins"].append(target_token)
    return {"status": "ok"}

@app.post("/remove_admin")
async def remove_admin(channel_slug: str = Form(...), user_nickname: str = Form(...), token: str = Form(...)):
    if token not in users or channel_slug not in channels or token != channels[channel_slug]["owner_token"]:
        raise HTTPException(status_code=403, detail="Только создатель")
    target_token = next((t for t, u in users.items() if u["nickname"] == user_nickname), None)
    if not target_token or target_token == channels[channel_slug]["owner_token"]:
        raise HTTPException(status_code=400, detail="Нельзя")
    if target_token in channels[channel_slug]["admins"]:
        channels[channel_slug]["admins"].remove(target_token)
    return {"status": "ok"}

@app.post("/transfer_ownership")
async def transfer_ownership(channel_slug: str = Form(...), new_owner_nickname: str = Form(...), token: str = Form(...)):
    if token not in users or channel_slug not in channels or token != channels[channel_slug]["owner_token"]:
        raise HTTPException(status_code=403, detail="Только создатель")
    new_token = next((t for t, u in users.items() if u["nickname"] == new_owner_nickname), None)
    if not new_token or new_token not in channels[channel_slug]["admins"]:
        raise HTTPException(status_code=400, detail="Новый владелец должен быть админом")
    old_owner = channels[channel_slug]["owner_token"]
    channels[channel_slug]["owner_token"] = new_token
    if old_owner not in channels[channel_slug]["admins"]:
        channels[channel_slug]["admins"].append(old_owner)
    return {"status": "ok"}

@app.get("/online_count")
async def online_count():
    return {"count": len(active_connections)}

@app.get("/history/{with_email}")
async def get_history(with_email: str, token: str):
    if token not in users:
        raise HTTPException(status_code=401, detail="Не авторизован")
    user_nick = users[token]["nickname"]
    result = [msg for msg in messages if not msg.get("channel", False) and ((msg["from_nick"] == user_nick and msg["to"] == with_email) or (msg["from_nick"] == with_email and msg["to"] == user_nick))]
    return result[-50:]

@app.websocket("/ws/{token}")
async def websocket_chat(websocket: WebSocket, token: str):
    if token not in users:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    active_connections[token] = websocket
    user_nick = users[token]["nickname"]
    await send_online_count()
    user_history = []
    for msg in messages[-30:]:
        if not msg.get("channel", False):
            if msg["from_nick"] == user_nick or msg["to"] == user_nick:
                user_history.append(msg)
        else:
            for slug, chan in channels.items():
                if token in chan["members"] and msg.get("channel_slug") == slug:
                    user_history.append(msg)
                    break
    await websocket.send_json({"type": "history", "messages": user_history})
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")
            if msg_type == "message":
                to = data.get("to", "")
                text = data.get("text", "")
                is_channel = data.get("is_channel", False)
                media_url = data.get("media_url", None)
                media_type = data.get("media_type", None)
                filename = data.get("filename", None)
                content = media_url if media_url else text
                if is_channel:
                    if to in channels:
                        channel = channels[to]
                        if channel["write_permission"] == "admin" and token not in channel["admins"]:
                            await websocket.send_json({"type": "error", "text": "❌ Только админы могут писать"})
                            continue
                        new_msg = {"from_token": token, "from_nick": user_nick, "to": to, "text": content, "time": datetime.now().strftime("%H:%M"), "channel": True, "channel_slug": to, "media_type": media_type, "filename": filename, "is_admin": token in channel["admins"], "is_owner": token == channel["owner_token"]}
                        messages.append(new_msg)
                        for member_token in channel["members"]:
                            if member_token in active_connections:
                                await active_connections[member_token].send_json({"type": "message", "from": user_nick, "text": content, "time": new_msg["time"], "channel": to, "media_type": media_type, "filename": filename, "is_admin": token in channel["admins"], "is_owner": token == channel["owner_token"]})
                else:
                    new_msg = {"from_token": token, "from_nick": user_nick, "to": to, "text": content, "time": datetime.now().strftime("%H:%M"), "channel": False, "media_type": media_type, "filename": filename}
                    messages.append(new_msg)
                    target_token = next((t for t, u in users.items() if u["nickname"] == to or u["email"] == to), None)
                    if target_token and target_token in active_connections:
                        await active_connections[target_token].send_json({"type": "message", "from": user_nick, "text": content, "time": new_msg["time"], "media_type": media_type, "filename": filename})
                    await websocket.send_json({"type": "sent", "to": to, "text": content})
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if token in active_connections:
            del active_connections[token]
        await send_online_count()

os.makedirs("static", exist_ok=True)

@app.get("/")
async def get_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.on_event("startup")
async def startup_event():
    thread = Thread(target=lambda: [time.sleep(3600) or None for _ in range(1000000)], daemon=True)
    thread.start()
    print("[STARTUP] Nodi запущен!")
