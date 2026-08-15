import asyncio
from datetime import datetime
import io
import os
import time
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from google import genai
from google.genai import types
import httpx
from PIL import Image

# ==================== 金鑰與資料庫設定 ====================
print("金鑰設定讀取中...")
FIREBASE_DB_URL = (
    "https://b-bot-website-default-rtdb.asia-southeast1.firebasedatabase.app"
)

bot_token = os.environ.get("BOT_TOKEN")
ai_chat = os.environ.get("AI_CHAT")
ai_web = os.environ.get("AI_WEB")
ai_photo = os.environ.get("AI_IMAGE")
ai_instruction = os.environ.get("AI_INSTRUCTION", "")

USER_TAGS = {
    "bally": os.environ.get("BALLY_TAG", ""),
    "ethan": os.environ.get("ETHAN_TAG", ""),
    "george": os.environ.get("GEORGE_TAG", ""),
    "jimmy": os.environ.get("JIMMY_TAG", ""),
    "other": os.environ.get("OTHER_TAG", ""),
}


# ==================== Firebase 通用工具函數 ====================
async def push_firebase_log(log_type, message, details=None):
  """推送 Log 紀錄到 Firebase /logs.json"""
  url = f"{FIREBASE_DB_URL}/logs.json"
  tz_gmt8 = ZoneInfo("Asia/Taipei")
  now_str = datetime.now(tz_gmt8).strftime("%Y-%m-%d %H:%M:%S")

  payload = {
      "timestamp": now_str,
      "type": log_type,  # 例如: "SYSTEM", "CHAT", "GAME", "ERROR", "SECURITY"
      "message": message,
      "details": details or {},
  }
  try:
    async with httpx.AsyncClient() as http_client:
      await http_client.post(url, json=payload, timeout=5.0)
  except Exception as e:
    print(f"❌ Firebase Log 寫入失敗: {e}")


async def update_bot_status(status_str, note=""):
  """更新機器人狀態到 Firebase /status.json"""
  url = f"{FIREBASE_DB_URL}/status.json"
  tz_gmt8 = ZoneInfo("Asia/Taipei")
  now_str = datetime.now(tz_gmt8).strftime("%Y-%m-%d %H:%M:%S")

  payload = {"status": status_str, "last_updated": now_str, "note": note}
  try:
    async with httpx.AsyncClient() as http_client:
      await http_client.put(url, json=payload, timeout=5.0)
  except Exception as e:
    print(f"❌ Firebase Status 更新失敗: {e}")


async def upload_to_firebase_async(payload):
  """專門給遊戲使用的 /botMessage.json"""
  url = f"{FIREBASE_DB_URL}/botMessage.json"
  try:
    async with httpx.AsyncClient() as http_client:
      response = await http_client.put(url, json=payload, timeout=10.0)
      return response.status_code == 200
  except Exception as e:
    print(f"Firebase 同步失敗: {e}")
    return False


async def delete_firebase_data_async():
  """清空遊戲資料 /botMessage.json"""
  url = f"{FIREBASE_DB_URL}/botMessage.json"
  try:
    async with httpx.AsyncClient() as http_client:
      response = await http_client.delete(url, timeout=10.0)
      return response.status_code in [200, 204]
  except Exception as e:
    print(f"Firebase 刪除連線失敗: {e}")
    return False


async def delete_firebase_logs_async():
  """清空所有 Log 紀錄 /logs.json"""
  url = f"{FIREBASE_DB_URL}/logs.json"
  try:
    async with httpx.AsyncClient() as http_client:
      response = await http_client.delete(url, timeout=10.0)
      return response.status_code in [200, 204]
  except Exception as e:
    print(f"Firebase 清空 Log 失敗: {e}")
    return False


# ==================== 載入 AI 區 ====================
def memories_reset():
  global model, api_chat, client_chat, chat, api_web, client_web, ai_vision, client_vision
  model = "gemini-3.1-flash-lite"

  api_chat = ai_chat
  client_chat = genai.Client(api_key=api_chat)
  chat = client_chat.chats.create(
      model=model,
      config=types.GenerateContentConfig(system_instruction=ai_instruction),
  )

  api_web = ai_web
  client_web = genai.Client(api_key=api_web)

  ai_vision = ai_photo
  client_vision = genai.Client(api_key=ai_vision)


# 初始化重置記憶
memories_reset()
print("=" * 20 + "重置記憶" + "=" * 20)

# ==================== ID 與變數設定 ====================
op = "bally1217"
op_id = 1053683294069338142
test_id = 1197511943523680338
g_id = 1165505919979888772
j_id = 1398184184547246103
CHANNEL_ID = 1504842926830784562
NORMAL_ID = 1504862333329998106
wk = True
last_trigger_time = 0


# ==================== 機器人核心類別 ====================
class MyBot(commands.Bot):

  def __init__(self, *, command_prefix: str, intents: discord.Intents):
    super().__init__(command_prefix=command_prefix, intents=intents)

  async def close(self):
    """複寫 close 事件，確保關機時自動寫入 Firebase 狀態與 Log"""
    await update_bot_status("offline", note="關機指令執行完畢，系統已離線")
    await push_firebase_log("SYSTEM", "機器人已關機/下線")
    await super().close()


intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix="", intents=intents)


# ==================== 登入開機事件 ====================
@bot.event
async def on_ready():
  print("=" * 20 + "登入機器人" + "=" * 20)

  # 更新開機狀態與 Log 到 Firebase
  await update_bot_status("online", note="成功開機並登入 Discord")
  await push_firebase_log(
      "SYSTEM", "機器人成功開機", {"bot_user": str(bot.user)}
  )

  channel = bot.get_channel(CHANNEL_ID)
  if channel and wk:
    tz_gmt8 = ZoneInfo("Asia/Taipei")
    current_time = datetime.now(tz_gmt8).strftime("%Y.%m.%d %H:%M %p")
    txt = (
        f"Time：{current_time} USER：BackstageIdentification"
        " TXT：成功開機，跟使用者說一句話，打招呼"
    )
    response = chat.send_message(txt)
    await channel.send(content=response.text)


# ==================== 訊息監聽事件 ====================
@bot.event
async def on_message(message):
  global last_trigger_time
  if message.author == bot.user:
    return

  dm = isinstance(message.channel, discord.DMChannel)
  m_bool = (
      message.content.startswith("B-bot去睡覺")
      or message.content.startswith("B-bot重置記憶")
      or message.content.startswith("B-bot玩遊戲")
      or message.content.startswith("B-bot刪遊戲")
      or message.content.startswith("B-bot刪Log")
      or message.content.startswith("B-bot清Log")
      or dm
      or message.content.startswith("!")
  )

  opdm = message.author.id == op_id and dm
  unuser = message.author.id == test_id or message.author.id == op_id
  channel = (
      message.channel.id == CHANNEL_ID or message.channel.id == NORMAL_ID
  )
  bot_c = message.channel.id == CHANNEL_ID

  tz_gmt8 = ZoneInfo("Asia/Taipei")
  current_time = datetime.now(tz_gmt8).strftime("%Y.%m.%d %H:%M %p")

  if m_bool:
    print("=" * 50)
    print(f"時間：{current_time} 收到訊息")

  # 1. 私訊處理
  if dm and not (unuser):
    await message.channel.send("在伺服器講話啦!")
    await push_firebase_log(
        "DM_REJECTED",
        f"非管理員 {message.author.display_name} 試圖私訊",
        {"content": message.content},
    )
    return
  elif message.content.startswith("B-bot去睡覺") and opdm:
    await message.channel.send("好喔")
    target_channel = bot.get_channel(CHANNEL_ID)
    await target_channel.send("害呀，Bally叫我去睡覺了，真可惡")

    await push_firebase_log(
        "SYSTEM", "管理員發送私訊關機指令", {"user": message.author.display_name}
    )
    await bot.close()
    return

  if not (channel) and m_bool:
    await message.channel.send("欸!不要在這裡吵我")
    return

  # 2. 關機指令
  if message.content.startswith("B-bot去睡覺"):
    if message.author.name == op:
      msg = await message.channel.send("蛤我不想要...")
      await asyncio.sleep(1.0)
      await msg.edit(content="💤")

      await push_firebase_log(
          "SYSTEM",
          "管理員發送公開關機指令",
          {"user": message.author.display_name},
      )
      await bot.close()
    else:
      await message.channel.send("我不要阿，哈哈")
      await push_firebase_log(
          "SECURITY",
          f"用戶 {message.author.display_name} 試圖關機（無權限）",
      )
    return

  # 3. 重置記憶
  if message.content.startswith("B-bot重置記憶"):
    await message.channel.send("記憶重置中.....")
    memories_reset()
    await message.channel.send("我是誰，我在哪裡？")
    await push_firebase_log(
        "ACTION", "重置記憶", {"user": message.author.display_name}
    )
    return

  # 4. 玩遊戲指令
  if message.content.startswith("B-bot玩遊戲"):
    game_mod = message.content.replace("B-bot玩遊戲", "", 1)
    current_time_sec = time.time()
    if current_time_sec - last_trigger_time < 45:
      await message.channel.send(
          f"有點bug，請等 {int(45 - (current_time_sec - last_trigger_time))} 秒後再試！"
      )
      return

    last_trigger_time = current_time_sec
    await message.channel.send("OK，相信我，我只要寫一下程式")

    await push_firebase_log(
        "GAME",
        "開始生成遊戲",
        {"user": message.author.display_name, "game_mod": game_mod},
    )

    await upload_to_firebase_async({
        "status": "thinking",
        "prompt_text": "AI 正在以 8-bit 像素風格撰寫完整的遊戲程式碼...",
        "html_code": "",
    })

    game_system_instruction = (
        f"請重現一款經典小遊戲{game_mod}，請讓玩家不須使用鍵盤，只用滑鼠\n"
        "程式不用太長，不用程式註解\n"
        "【完整閉合】：JavaScript 必須 splice 刪除防止卡死。在 <script> 的最後一行必須直接呼叫 initGame(); 啟動。\n"
        "【UI 美術套版】：盡量設計美觀，可使用少量css，不要寫太多\n"
        "【強迫極簡一體化】：你必須把 <style>、HTML 身體、<script> 全部寫在同一個檔案內。\n"
        "在 JS 開頭強制加上 window.focus(); 事件監聽一律綁在 window 上，確保一打開網頁就能立刻控制。\n"
        "如果有滑鼠點擊，計算 Canvas 座標必須使用 `e.clientX - canvas.getBoundingClientRect().left`，不准用 e.offsetX。\n"
        "請直接輸出完整網頁 HTML 原始碼，絕對不要包含任何 markdown 標記。(包含```)"
    )

    try:
      config = types.GenerateContentConfig(
          max_output_tokens=100000, temperature=0.8
      )
      response = await client_web.aio.models.generate_content(
          model="gemini-2.5-flash",
          contents=f"{game_system_instruction}",
          config=config,
      )
      raw_html = response.text.strip() if response.text else ""
      if raw_html.startswith("```html"):
        raw_html = raw_html.replace("```html", "", 1)
      if raw_html.endswith("```"):
        raw_html = raw_html[::-1].replace("```"[::-1], "", 1)[::-1]

      if (
          "</script>" in raw_html
          and "</body>" in raw_html
          and "</html>" in raw_html
      ):
        await upload_to_firebase_async({
            "status": "done",
            "prompt_text": "NES 像素風小遊戲",
            "html_code": raw_html,
        })
        await message.channel.send(
            "我OK了！點這個-->**[網站](https://ballyblish.github.io/b-bot-game/)**"
        )
        await push_firebase_log("GAME", "遊戲生成成功")
      else:
        await message.channel.send("開發失敗...(可能是你要求太多)")
        await push_firebase_log("GAME", "遊戲生成失敗（HTML不完整）")
    except Exception as e:
      print(f"生成失敗: {e}")
      await message.channel.send("開發失敗...(可能是你要求太多)")
      await push_firebase_log("ERROR", f"遊戲生成異常: {e}")
    return

  # 5. 刪遊戲指令
  if message.content.startswith("B-bot刪遊戲"):
    if unuser:
      msg = await message.channel.send("蛤，我寫得很辛苦...")
      success = await delete_firebase_data_async()
      if success:
        await msg.edit(content="啊啊啊~沒了")
        await push_firebase_log(
            "GAME", "遊戲已刪除", {"user": message.author.display_name}
        )
      else:
        await msg.edit(content="網站連不到，刪不了，ㄏㄏ")
    else:
      await message.channel.send("我不要阿，哈哈")
    return

  # 6. 清空/刪除 Log 指令
  if message.content.startswith("B-bot刪Log") or message.content.startswith(
      "B-bot清Log"
  ):
    if unuser:
      msg = await message.channel.send("正在清空 Firebase Log 紀錄...")
      success = await delete_firebase_logs_async()
      if success:
        await msg.edit(content="🧹 Firebase Log 已成功清空！")
        await push_firebase_log(
            "SYSTEM",
            "Log 已被管理員手動清空",
            {"user": message.author.display_name},
        )
      else:
        await msg.edit(content="❌ 清空失敗，請檢查 Firebase 連線！")
    else:
      await message.channel.send("你沒有權限刪除 Log 喔，哈哈！")
    return

  # 7. 對話與圖片對答
  if bot_c or message.content.startswith("!"):
    txt = (
        message.content.replace("!", "", 1)
        if message.content.startswith("!")
        else message.content
    )
    user_id = message.author.id

    if user_id == op_id:
      tag = USER_TAGS["bally"]
    elif user_id == test_id:
      tag = USER_TAGS["ethan"]
    elif user_id == g_id:
      tag = USER_TAGS["george"]
    elif user_id == j_id:
      tag = USER_TAGS["jimmy"]
    else:
      tag = USER_TAGS["other"]

    async with message.channel.typing():
      image_description = ""
      if message.attachments:
        for attachment in message.attachments:
          if any(
              attachment.filename.lower().endswith(ext)
              for ext in [".png", ".jpg", ".jpeg", ".webp"]
          ):
            try:
              async with httpx.AsyncClient() as http_client:
                img_resp = await http_client.get(
                    attachment.url, timeout=10.0
                )
                if img_resp.status_code == 200:
                  img = Image.open(io.BytesIO(img_resp.content))
                  v_response = (
                      await client_vision.aio.models.generate_content(
                          model=model,
                          contents=[
                              img,
                              "描述這張圖片：一句話蓋擴換行後再加上四到十項重點或細節。",
                          ],
                      )
                  )
                  image_description += v_response.text.strip()
            except Exception as e:
              print(f"❌ 圖片處理失敗: {e}")

      ai_txt = (
          f"Time:{current_time} USER:{tag} TXT:{txt} {image_description}"
      )
      response = chat.send_message(ai_txt)
      await message.channel.send(content=response.text)

      # 紀錄對話 Log 到 Firebase
      await push_firebase_log(
          "CHAT",
          f"收到來自 {message.author.display_name} 的訊息",
          {
              "user_id": str(user_id),
              "user_tag": tag,
              "user_prompt": txt,
              "has_image": bool(image_description),
              "bot_response": response.text,
          },
      )


bot.run(bot_token)