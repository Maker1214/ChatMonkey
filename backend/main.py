# main.py

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
import openai

# ========== 基本設定 ==========
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
if openai.api_key is None:
    raise RuntimeError("⚠️ 找不到 OpenAI API 金鑰，請檢查 .env 設定")

DATABASE_URL = "mysql+pymysql://username:password@localhost/chat_db"  # 👉 修改為你的帳號密碼
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ========== 資料表定義 ==========
class Chat(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64))
    message = Column(Text)
    role = Column(String(10))  # user 或 bot
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# ========== FastAPI 應用 ==========
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ========== 接收 POST /chat ==========
class ChatInput(BaseModel):
    user_id: str
    message: str

@app.post("/chat")
async def chat(input: ChatInput):
    db = SessionLocal()

    # 儲存使用者訊息
    user_chat = Chat(user_id=input.user_id, message=input.message, role="user")
    db.add(user_chat)
    db.commit()

    # 呼叫 OpenAI API 取得回應
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": input.message}]
        )
        bot_reply = response.choices[0].message.content
    except Exception as e:
        bot_reply = "呼叫 AI 失敗：" + str(e)

    # 儲存 AI 回應
    bot_chat = Chat(user_id=input.user_id, message=bot_reply, role="bot")
    db.add(bot_chat)
    db.commit()
    db.close()

    return {"reply": bot_reply}

# ========== 接收 GET /history ==========
@app.get("/history")
async def history(user_id: str = Query(...)):
    db = SessionLocal()
    chats = db.query(Chat).filter(Chat.user_id == user_id).order_by(Chat.timestamp.asc()).all()
    db.close()

    result = [
        {"role": c.role, "message": c.message, "timestamp": c.timestamp.isoformat()}
        for c in chats
    ]
    return {"history": result}
