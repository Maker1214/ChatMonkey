# main.py

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
from openai import OpenAI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import hashlib

# ========== 基本設定 ==========
# 載入 .env 檔案中的環境變數 到 Python 程式中，通常用在設定檔、金鑰或資料庫連線等敏感資訊的管理上。
# load_dotenv() 會讀取 .env 檔，把裡面的變數寫入系統的環境變數（os.environ），讓你的程式可以透過 os.getenv() 取得。
load_dotenv()
api_key=os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("找不到 OPENAI_API_KEY，請確認 .env 設定")
client = OpenAI(api_key = api_key)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("找不到 DATABASE_URL，請確認 .env 設定")

CORRECT_PASSWORD = os.getenv("PASSWORD")
if not CORRECT_PASSWORD:
    raise RuntimeError("找不到 PASSWORD，請確認 .env 設定")
# create_engine 是 SQLAlchemy 提供的一個函數，用來建立一個與資料庫的連線引擎（Engine）。這是連接資料庫的第一步，後續可以透過這個引擎執行 SQL 查詢或透過 ORM 進行操作。
engine = create_engine(DATABASE_URL, echo=False) #echo=False 代表不會印出 SQL 查詢語句到 uvicorn console
# Session 是你和資料庫之間的一個臨時會話連線，用來處理所有資料的查詢與變更操作，並負責管理資料的狀態（新增、修改、刪除）。
# Session 就像是一個「編輯器」，你在這個 Session 裡做的操作（新增資料、改欄位、刪除）都只是暫存在編輯器裡，session.commit() 就像按下「儲存」鍵，才會把變更寫進實體資料庫。
SessionLocal = sessionmaker(bind=engine)
# declarative_base() 是 SQLAlchemy 用來建立 ORM 模型的「基底類別」，你定義的所有資料表都要繼承它。
# why ORM(Object-Relational Mapping)? 
# 1. ORM 自動處理參數轉義，幾乎不可能發生 SQL injection
# 2. ORM 幫你「把資料表當成類別，把欄位當成屬性」，你就不用寫一堆 SQL，也不需手動轉換資料格式
Base = declarative_base()

# ========== 資料表定義 ==========
# Chat會繼承declarative_base()所建立的ORM 模型
class Chat(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64))
    message = Column(Text)
    role = Column(String(10))  # user 或 bot
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

# 在資料庫中建立 chat_history 表
Base.metadata.create_all(bind=engine)

# ========== FastAPI 應用 ==========
app = FastAPI()
app.add_middleware(
    CORSMiddleware, # 允許前端跨網域請求（例如本機前端與後端不同 port)
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# ========== 掛載靜態檔案資料夾 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # -> /backend
ROOT_DIR = os.path.dirname(BASE_DIR) # -> /CHATBOT
STATIC_DIR = os.path.join(ROOT_DIR, "frontend") # -> /CHATBOT/frontend
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# ========== 驗證密碼 ==========
@app.post("/verify")
async def verify_password(request: Request):
    data = await request.json()
    if data.get("password") == CORRECT_PASSWORD:
        return JSONResponse({"status": "ok"})
    else:
        return JSONResponse({"status": "fail"}, status_code=401)
    

# ========== 接收 POST /chat ==========
# BaseModel : 定義 API 接收 / 回傳資料格式的基礎，它會自動幫你檢查資料正確性，並提供 JSON 轉換等功能。
# Pydantic 的 BaseModel 就是 FastAPI 的資料驗證核心，它讓你不需要自己手動檢查資料格式或類型錯誤。
class ChatInput(BaseModel):
    user_id: str
    message: str

@app.post("/chat")
async def chat(input: ChatInput):
    db = SessionLocal()

    # 查詢該 user_id 已發送次數
    count = db.query(Chat).filter(Chat.user_id == input.user_id, Chat.role == "user").count()
    
    MAX_MESSAGES = 20
    if count >= MAX_MESSAGES:  # 設定每個使用者最多可發送 20 次
        db.close()
        return JSONResponse({"error": "已達到發送上限"}, status_code=403)

    # 儲存使用者訊息
    user_chat = Chat(user_id=input.user_id, message=input.message, role="user")
    db.add(user_chat)
    db.commit()

    # 呼叫 OpenAI GPT 模型取得回應
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": input.message}
            ]
        )
        bot_reply = response.choices[0].message.content
    except Exception as e:
        bot_reply = f"呼叫 AI 失敗：{e}"

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
