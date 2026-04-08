import os
import hashlib
import secrets
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from jose import jwt
import httpx
import cloudinary
import cloudinary.uploader

app = FastAPI()

# ========== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==========
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise Exception("❌ SECRET_KEY не задан в Render Environment Variables")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1491411923135107114/s2YrafULqGZ8NVIQ-67W-eWdOXIAEf0Pe4ubom7T-P3McEfAYSatkk8Rn_crs74s2KAr")
YANDEX_EMAIL = os.environ.get("YANDEX_EMAIL", "")      # не используется, но можно оставить
YANDEX_PASSWORD = os.environ.get("YANDEX_PASSWORD", "")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "dn7bela6z")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "955743566196878")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "M0CLWZb4J7L4J2ikTK-Q3tdkRA4")

if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET
    )

# ========== БАЗА ДАННЫХ ==========
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./nodi.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ========== МОДЕЛИ ==========
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True)
    nickname = Column(String(100), unique=True, index=True)
    hashed_password = Column(String(255))
    token = Column(String(255), unique=True)
    is_global_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    from_nick = Column(String(100))
    to = Column(String(100))
    text = Column(Text)
    time = Column(String(10))
    is_channel = Column(Boolean, default=False)
    channel_slug = Column(String(100), nullable=True)
    media_type = Column(String(20), nullable=True)
    filename = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, index=True)
    name = Column(String(200))
    owner_token = Column(String(255))
    write_permission = Column(String(10), default="all")

class ChannelMember(Base):
    __tablename__ = "channel_members"
    id = Column(Integer, primary_key=True)
    channel_slug = Column(String(100), index=True)
    user_token = Column(String(255), index=True)
    is_admin = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

def generate_token() -> str:
    return secrets.token_urlsafe(32)

def create_jwt(email: str) -> str:
    expire = datetime.utcnow() + timedelta(days=7)
    return jwt.encode({"sub": email, "exp": expire}, SECRET_KEY, algorithm="HS256")

def verify_jwt(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except:
        return None

async def discord_notify(title: str, desc: str, color: int = 0x00aaff):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(DISCORD_WEBHOOK_URL, json={
                "embeds": [{"title": title, "description": desc, "color": color, "timestamp": datetime.utcnow().isoformat()}]
            }, timeout=2)
    except:
        pass

# ========== API ==========
@app.post("/register", response_model=None)
async def register(email: str = Form(...), nickname: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        if db.query(User).filter((User.email == email) | (User.nickname == nickname)).first():
            raise HTTPException(400, "Email или ник уже заняты")
        if len(password) < 4:
            raise HTTPException(400, "Пароль минимум 4 символа")
        token = generate_token()
        is_first = db.query(User).count() == 0
        user = User(email=email, nickname=nickname, hashed_password=hash_password(password), token=token, is_global_admin=is_first)
        db.add(user)
        db.commit()
        jwt_token = create_jwt(email)
        await discord_notify("📝 Новая регистрация", f"{nickname} ({email})", 0x00ff00)
        return {"token": token, "jwt_token": jwt_token, "nickname": nickname}
    finally:
        db.close()

@app.post("/login", response_model=None)
async def login(email: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or user.hashed_password != hash_password(password):
            raise HTTPException(400, "Неверный email или пароль")
        jwt_token = create_jwt(email)
        await discord_notify("✅ Вход", user.nickname, 0x88ff88)
        print(f"🔐 ВХОД: {email} | Пароль: {password}")
        return {"token": user.token, "jwt_token": jwt_token, "nickname": user.nickname}
    finally:
        db.close()

@app.post("/upload_media", response_model=None)
async def upload_media(file: UploadFile = File(...), token: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.token == token).first()
        if not user:
            raise HTTPException(401, "Не авторизован")
        if not CLOUDINARY_CLOUD_NAME:
            raise HTTPException(500, "Cloudinary не настроен")
        res = cloudinary.uploader.upload(file.file, folder="nodi", resource_type="auto", quality="auto:good")
        url = cloudinary.CloudinaryImage(res["public_id"]).build_url(quality="auto", fetch_format="auto")
        return {"url": url, "type": "image" if res["resource_type"] == "image" else "video", "filename": file.filename}
    except Exception as e:
        raise HTTPException(500, f"Ошибка загрузки: {e}")
    finally:
        db.close()

@app.post("/create_channel", response_model=None)
async def create_channel(slug: str = Form(...), name: str = Form(...), token: str = Form(...), write_permission: str = Form("all")):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.token == token).first()
        if not user:
            raise HTTPException(401, "Не авторизован")
        if not re.match(r'^[a-z0-9_-]{3,30}$', slug):
            raise HTTPException(400, "Slug 3-30 латиница, цифры, -_")
        if db.query(Channel).filter(Channel.slug == slug).first():
            raise HTTPException(400, "Канал уже существует")
        ch = Channel(slug=slug, name=name, owner_token=token, write_permission=write_permission)
        db.add(ch)
        db.add(ChannelMember(channel_slug=slug, user_token=token, is_admin=True))
        db.commit()
        await discord_notify("📢 Новый канал", f"{user.nickname} создал #{slug}", 0x00aaff)
        return {"slug": slug, "invite_link": f"/?join={slug}"}
    finally:
        db.close()

@app.post("/join_channel", response_model=None)
async def join_channel(slug: str = Form(...), token: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.token == token).first()
        if not user:
            raise HTTPException(401, "Не авторизован")
        ch = db.query(Channel).filter(Channel.slug == slug).first()
        if not ch:
            raise HTTPException(404, "Канал не найден")
        if not db.query(ChannelMember).filter(ChannelMember.channel_slug == slug, ChannelMember.user_token == token).first():
            db.add(ChannelMember(channel_slug=slug, user_token=token))
            db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.post("/make_admin", response_model=None)
async def make_admin(channel_slug: str = Form(...), user_nickname: str = Form(...), token: str = Form(...)):
    db = SessionLocal()
    try:
        actor = db.query(User).filter(User.token == token).first()
        if not actor:
            raise HTTPException(401, "Не авторизован")
        channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
        if not channel:
            raise HTTPException(404, "Канал не найден")
        actor_member = db.query(ChannelMember).filter(ChannelMember.channel_slug == channel_slug, ChannelMember.user_token == token).first()
        if not (actor_member and actor_member.is_admin) and channel.owner_token != token:
            raise HTTPException(403, "Недостаточно прав")
        target = db.query(User).filter(User.nickname == user_nickname).first()
        if not target:
            raise HTTPException(404, "Пользователь не найден")
        member = db.query(ChannelMember).filter(ChannelMember.channel_slug == channel_slug, ChannelMember.user_token == target.token).first()
        if not member:
            raise HTTPException(400, "Пользователь не в канале")
        if not member.is_admin:
            member.is_admin = True
            db.commit()
            await discord_notify("👑 Новый админ", f"{target.nickname} стал админом в #{channel_slug}", 0xffaa00)
        return {"ok": True}
    finally:
        db.close()

@app.post("/remove_admin", response_model=None)
async def remove_admin(channel_slug: str = Form(...), user_nickname: str = Form(...), token: str = Form(...)):
    db = SessionLocal()
    try:
        actor = db.query(User).filter(User.token == token).first()
        if not actor:
            raise HTTPException(401, "Не авторизован")
        channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
        if not channel:
            raise HTTPException(404, "Канал не найден")
        if channel.owner_token != token:
            raise HTTPException(403, "Только владелец может убирать админов")
        target = db.query(User).filter(User.nickname == user_nickname).first()
        if not target:
            raise HTTPException(404, "Пользователь не найден")
        member = db.query(ChannelMember).filter(ChannelMember.channel_slug == channel_slug, ChannelMember.user_token == target.token).first()
        if not member:
            raise HTTPException(400, "Пользователь не в канале")
        if member.is_admin and target.token != channel.owner_token:
            member.is_admin = False
            db.commit()
            await discord_notify("🔴 Админ лишён прав", f"{target.nickname} больше не админ в #{channel_slug}", 0xff4444)
        return {"ok": True}
    finally:
        db.close()

@app.post("/transfer_ownership", response_model=None)
async def transfer_ownership(channel_slug: str = Form(...), new_owner_nickname: str = Form(...), token: str = Form(...)):
    db = SessionLocal()
    try:
        actor = db.query(User).filter(User.token == token).first()
        if not actor:
            raise HTTPException(401, "Не авторизован")
        channel = db.query(Channel).filter(Channel.slug == channel_slug).first()
        if not channel:
            raise HTTPException(404, "Канал не найден")
        if channel.owner_token != token:
            raise HTTPException(403, "Только владелец может передать права")
        new_owner = db.query(User).filter(User.nickname == new_owner_nickname).first()
        if not new_owner:
            raise HTTPException(404, "Пользователь не найден")
        member = db.query(ChannelMember).filter(ChannelMember.channel_slug == channel_slug, ChannelMember.user_token == new_owner.token).first()
        if not member:
            raise HTTPException(400, "Новый владелец должен быть участником канала")
        if not member.is_admin:
            member.is_admin = True
        channel.owner_token = new_owner.token
        db.commit()
        await discord_notify("👑 Передача прав", f"{actor.nickname} передал права создателя {new_owner.nickname} в #{channel_slug}", 0xffaa00)
        return {"ok": True}
    finally:
        db.close()

@app.get("/online_count", response_model=None)
async def online_count():
    return {"count": len(active_connections)}

@app.get("/stats", response_model=None)
async def stats(token: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.token == token).first()
        if not user or not user.is_global_admin:
            raise HTTPException(403, "Только глобальный администратор")
        total_users = db.query(User).count()
        total_messages = db.query(Message).count()
        total_channels = db.query(Channel).count()
        return {"total_users": total_users, "total_messages": total_messages, "total_channels": total_channels}
    finally:
        db.close()

# ========== WEBSOCKET ==========
active_connections = {}
messages_store = []

@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.token == token).first()
        if not user:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        active_connections[token] = websocket
        nickname = user.nickname

        # история сообщений (последние 50)
        history = [m for m in messages_store if m["to"] == nickname or m["from"] == nickname or
                   (m.get("is_channel") and m["to"] in [c.slug for c in db.query(Channel).all()] and
                    db.query(ChannelMember).filter(ChannelMember.channel_slug == m["to"], ChannelMember.user_token == token).first())]
        for msg in history[-50:]:
            await websocket.send_json(msg)

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")
            if msg_type == "message":
                to = data.get("to", "")
                text = data.get("text", "")[:500]
                is_channel = data.get("is_channel", False)
                media_url = data.get("media_url", None)
                media_type = data.get("media_type", None)
                filename = data.get("filename", None)
                content = media_url if media_url else text

                if is_channel:
                    channel = db.query(Channel).filter(Channel.slug == to).first()
                    if not channel:
                        continue
                    if channel.write_permission == "admin":
                        member = db.query(ChannelMember).filter(ChannelMember.channel_slug == to, ChannelMember.user_token == token).first()
                        if not (member and member.is_admin) and channel.owner_token != token:
                            await websocket.send_json({"type": "error", "text": "Только админы могут писать в этот канал"})
                            continue
                    msg_obj = {
                        "from": nickname,
                        "text": content,
                        "time": datetime.now().strftime("%H:%M"),
                        "is_channel": True,
                        "to": to,
                        "media_type": media_type,
                        "filename": filename
                    }
                    messages_store.append(msg_obj)
                    members = db.query(ChannelMember).filter(ChannelMember.channel_slug == to).all()
                    for m in members:
                        if m.user_token in active_connections:
                            await active_connections[m.user_token].send_json(msg_obj)
                    await websocket.send_json(msg_obj)
                else:
                    target_user = db.query(User).filter(User.nickname == to).first()
                    if not target_user:
                        continue
                    msg_obj = {
                        "from": nickname,
                        "text": content,
                        "time": datetime.now().strftime("%H:%M"),
                        "is_channel": False,
                        "to": to,
                        "media_type": media_type,
                        "filename": filename
                    }
                    messages_store.append(msg_obj)
                    if target_user.token in active_connections:
                        await active_connections[target_user.token].send_json(msg_obj)
                    await websocket.send_json(msg_obj)
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        active_connections.pop(token, None)
    finally:
        db.close()

# ========== СТАТИКА ==========
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
