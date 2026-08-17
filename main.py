# 模組載入
import asyncio
from datetime import datetime
import io
import os
import re
import socketserver
import threading
import time
from zoneinfo import ZoneInfo
import http.server

import discord
from discord.ext import commands
from google import genai
from google.genai import types
import httpx
from PIL import Image

# ==================== 金鑰與資料庫設定 ====================
FIREBASE_DB_URL = "https://b-bot-website-default-rtdb.asia-southeast1.firebasedatabase.app"

def get_env(key, default=""):
    key_upper = key.upper()
    key_lower = key.lower()
    try:
        from google.colab import userdata
        val = userdata.get(key_lower) or userdata.get(key_upper)
        if val:
            return val
    except Exception:
        pass

    # 2. 如果不是 Colab 環境，從 os.environ 讀取
    return os.environ.get(key_upper) or os.environ.get(key_lower, default)

print("金鑰設定讀取中...")
bot_token = get_env("BOT_TOKEN")
ai_chat = get_env("AI_CHAT")
ai_web = get_env("AI_WEB")
ai_photo = get_env("AI_IMAGE")
ai_instruction = get_env("AI_INSTRUCTION", "")

USER_TAGS = {
    "bally": get_env("BALLY_TAG"),
    "ethan": get_env("ETHAN_TAG"),
    "george": get_env("GEORGE_TAG"),
    "jimmy": get_env("JIMMY_TAG"),
    "other": get_env("OTHER_TAG"),
}


# ==================== Firebase 通用工具函數 ====================
async def push_firebase_log(log_type, message, details=None):
    """推送 Log 紀錄到 Firebase /logs.json"""
    url = f"{FIREBASE_DB_URL}/logs.json"
    tz_gmt8 = ZoneInfo("Asia/Taipei")
    now_str = datetime.now(tz_gmt8).strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "timestamp": now_str,
        "type": log_type,
        "message": message,
        "details": details or {},
    }
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(url, json=payload, timeout=5.0)
    except Exception as e:
        print(f"Firebase Log 寫入失敗: {e}")


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
        print(f"Firebase Status 更新失敗: {e}")


async def upload_to_firebase_async(payload):
    """專門給遊戲使用的 /botMessage.json"""
    url = f"{FIREBASE_DB_URL}/botMessage.json"
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.put(url, json=payload, timeout=10.0)
            if response.status_code == 200:
                print("=" * 20 + "Firebase連線成功" + "=" * 20)
                return True
            return False
    except Exception as e:
        print(f"Firebase 同步失敗: {e}")
        return False


async def delete_firebase_data_async():
    """清空遊戲資料 /botMessage.json"""
    url = f"{FIREBASE_DB_URL}/botMessage.json"
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.delete(url, timeout=10.0)
            if response.status_code in [200, 204]:
                print("Firebase 資料已成功清空！")
                return True
            else:
                print(f"刪除失敗，伺服器回應狀態碼: {response.status_code}")
                return False
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


# 重置記憶
memories_reset()
print("=" * 20 + "重置記憶" + "=" * 20)

# ==================== ID 與變數設定 ====================
print("=" * 20 + "使用者ID設定" + "=" * 20)
op = "bally1217"
op_id = 1053683294069338142
test_id = 1197511943523680338
g_id = 1165505919979888772
j_id = 1398184184547246103
CHANNEL_ID = 1505199666709401751
NORMAL_ID = 1504842926830784562
wk = True
last_trigger_time = 0


# ==================== 機器人核心類別 ====================
class MyBot(commands.Bot):
    def __init__(self, *, command_prefix: str, intents: discord.Intents):
        super().__init__(command_prefix=command_prefix, intents=intents)

    async def close(self):
        """關機時自動寫入 Firebase 狀態與 Log"""
        await update_bot_status("offline", note="機器人關機下線")
        await push_firebase_log("SYSTEM", "機器人已關機/下線")
        await super().close()


intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(command_prefix="", intents=intents)
print("=" * 20 + "機器人設定成功" + "=" * 20)
print("=" * 20 + "Firebase函數設定成功" + "=" * 20)


# ==================== 登入開機事件 ====================
@bot.event
async def on_ready():
    print("=" * 20 + "登入機器人" + "=" * 20)
    await update_bot_status("online", note="成功開機並登入 Discord")
    await push_firebase_log(
        "SYSTEM", "機器人成功開機", {"bot_user": str(bot.user)}
    )

    channel = bot.get_channel(CHANNEL_ID)
    if channel and wk:
        await channel.send("大家好啊，我開機了")


# ==================== 訊息監聽事件 ====================
print("=" * 20 + "機器人啟動" + "=" * 20)

@bot.event
async def on_message(message):
    global last_trigger_time
    # 忽略機器人自己的訊息
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
    channel = message.channel.id == CHANNEL_ID or message.channel.id == NORMAL_ID
    bot_c = message.channel.id == CHANNEL_ID

    tz_gmt8 = ZoneInfo("Asia/Taipei")
    current_time = datetime.now(tz_gmt8).strftime("%Y.%m.%d %H:%M %p")

    # 控制台印出日誌起頭
    if m_bool:
        print("=" * 50)
        print(f"時間：{current_time} 收到訊息")

    # ==================== 1. 私訊處理 ====================
    if dm and not unuser:
        await message.channel.send("在伺服器講話啦!")
        m_user = message.author.display_name
        txt = message.content.replace("\n", " ")
        print(f"非管理員用戶：{m_user} - 私訊：{txt}")
        await push_firebase_log(
            "DM_REJECTED",
            f"非管理員 {m_user} 試圖私訊",
            {"content": message.content, "user_id": str(message.author.id)},
        )
        return

    elif message.content.startswith("B-bot去睡覺") and opdm:
        m_user = message.author.display_name
        print(f"管理員：{m_user} - 私訊關機指令")
        op_send = await bot.fetch_user(op_id)
        await op_send.send("好喔")
        target_channel = bot.get_channel(CHANNEL_ID)
        await target_channel.send("等一下，Bally私訊我")
        await asyncio.sleep(3.0)
        await target_channel.send(content="害呀，Bally叫我去睡覺了，真可惡")
        await asyncio.sleep(3.0)
        await target_channel.send(content="💤💤💤")

        # 【Firebase Log】私訊關機紀錄
        await push_firebase_log(
            "SYSTEM", "管理員發送私訊關機指令", {"user": m_user}
        )
        await bot.close()
        return

    elif message.content.startswith("B-bot說\n") and dm and unuser:
        txt = message.content.replace("B-bot說\n", "", 1)
        m_user = message.author.display_name
        print(f"管理員：{m_user} - 公布訊息：{txt}")
        op_send = await bot.fetch_user(message.author.id)
        await op_send.send("好喔")
        target_channel = bot.get_channel(CHANNEL_ID)
        await target_channel.send("等一下，有人私訊我")
        await asyncio.sleep(3.0)
        await target_channel.send(
            content=f"{op_send.display_name} 他跟我說要告訴你們：\n**{txt}**"
        )

        # 【Firebase Log】私訊廣播紀錄
        await push_firebase_log(
            "BROADCAST",
            f"管理員 {m_user} 發送廣播公告",
            {"content": txt},
        )
        return

    elif dm and unuser:
        m_user = message.author.display_name
        txt = message.content.replace("\n", " ")
        print(f"管理員：{m_user} - 私訊亂講話：{txt}")
        await message.channel.send("可不可以講我聽得懂的")
        return

    # ==================== 2. 非正確頻道 ====================
    if not channel and m_bool:
        m_user = message.author.display_name
        txt = message.content.replace("\n", " ")
        print(f"帳號：{m_user} - 在非正確頻道呼喚：{txt}")
        await message.channel.send("欸!不要在這裡吵我")

        # 【Firebase Log】跨頻道呼喚紀錄
        await push_firebase_log(
            "SECURITY",
            f"用戶 {m_user} 在非指定頻道觸發指令",
            {"channel_id": str(message.channel.id), "content": txt},
        )
        return

    # ==================== 3. 關機指令 ====================
    if message.content.startswith("B-bot去睡覺"):
        m_user = message.author.display_name
        if message.author.name == op:
            print(f"管理員：{m_user} - 公開使用關機指令")
            msg = await message.channel.send("蛤我不想要...")
            await asyncio.sleep(1.0)
            await msg.edit(content="💤")

            # 【Firebase Log】公開關機紀錄
            await push_firebase_log(
                "SYSTEM", "管理員發送公開關機指令", {"user": m_user}
            )
            await bot.close()
        else:
            print(f"帳號：{m_user} - 非管理員公開試圖關機")
            await message.channel.send("我不要阿，哈哈")

            # 【Firebase Log】無權限關機警告
            await push_firebase_log(
                "SECURITY", f"用戶 {m_user} 試圖關機（權限不足）"
            )
        return

    # ==================== 4. 重置記憶 ====================
    if message.content.startswith("B-bot重置記憶"):
        m_user = message.author.display_name
        print(f"帳號：{m_user} - 使用重置記憶指令")
        await message.channel.send("欸!幹嘛啦!我的記憶要被重置了!")
        memories_reset()
        await message.channel.send("記憶重置中.....")
        await asyncio.sleep(3.0)
        await message.channel.send("我是誰，我在哪裡？")

        # 【Firebase Log】重置記憶紀錄
        await push_firebase_log(
            "ACTION", "AI 對話記憶已重置", {"user": m_user}
        )
        return

    # ==================== 5. 玩遊戲生成 ====================
    if message.content.startswith("B-bot玩遊戲"):
        game_mod = message.content.replace("B-bot玩遊戲", "", 1)
        m_user = message.author.display_name
        print(f"帳號：{m_user} - 使用寫遊戲程式指令：{game_mod}")

        current_time_sec = time.time()
        time_passed = current_time_sec - last_trigger_time
        if time_passed < 45:
            remaining = int(45 - time_passed)
            await message.channel.send(
                f"有點bug，請等 {remaining} 秒後再試！"
            )
            return

        last_trigger_time = current_time_sec
        await message.channel.send("OK，相信我，我只要寫一下程式")

        # 【Firebase Log】開始寫遊戲紀錄
        await push_firebase_log(
            "GAME",
            "開始生成遊戲程式碼",
            {"user": m_user, "prompt": game_mod},
        )

        await upload_to_firebase_async({
            "status": "thinking",
            "prompt_text": "AI 正在撰寫 HTML/JS 遊戲...",
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
                model="gemini-3.1-flash-lite",
                contents=game_system_instruction,
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
                    "prompt_text": f"小遊戲：{game_mod}",
                    "html_code": raw_html,
                })
                await message.channel.send(
                    "我OK了！點這個-->**[網站](https://ballyblish.github.io/b-bot-game/)**"
                )
                print("生成完成 - 可喜可賀")

                # 【Firebase Log】遊戲生成成功
                await push_firebase_log(
                    "GAME", "遊戲生成成功", {"game_mod": game_mod}
                )
            else:
                print("生成不完整 - 視為失敗")
                await message.channel.send("開發失敗...(可能是你要求太多)")
                await message.channel.send("欸<@1053683294069338142>修理一下")

                # 【Firebase Log】遊戲生成不完整失敗
                await push_firebase_log(
                    "GAME",
                    "遊戲生成失敗（HTML 標籤不完整）",
                    {"prompt": game_mod},
                )

        except Exception as e:
            print(f"生成失敗: {e}")
            await message.channel.send("開發失敗...(可能是你要求太多)")
            await message.channel.send("欸<@1053683294069338142>修理一下")
            await upload_to_firebase_async({"status": "error", "html_code": ""})

            # 【Firebase Log】遊戲生成例外錯誤
            await push_firebase_log(
                "ERROR", f"遊戲生成異常: {str(e)}", {"prompt": game_mod}
            )
        return

    # ==================== 6. 刪除遊戲 ====================
    if message.content.startswith("B-bot刪遊戲"):
        m_user = message.author.display_name
        if unuser:
            msg = await message.channel.send("蛤，我寫得很辛苦...")
            print(f"管理員：{m_user} - 使用刪除遊戲指令")
            success = await delete_firebase_data_async()
            await asyncio.sleep(3.0)
            if success:
                print("網頁已洗白")
                await msg.edit(content="啊啊啊~沒了")

                # 【Firebase Log】刪除遊戲成功
                await push_firebase_log("GAME", "遊戲已被管理員刪除/洗白", {"user": m_user})
            else:
                print("刪除失敗了")
                await msg.edit(content="網站連不到，刪不了，ㄏㄏ")
        else:
            print(f"帳號 {m_user} 非管理員試圖刪除遊戲")
            await message.channel.send("我不要阿，哈哈")

            # 【Firebase Log】非管理員刪除遊戲警告
            await push_firebase_log(
                "SECURITY", f"用戶 {m_user} 試圖刪除遊戲（無權限）"
            )
        return

    # ==================== 7. 清空/刪除 Log 指令 ====================
    if message.content.startswith("B-bot刪Log") or message.content.startswith(
        "B-bot清Log"
    ):
        m_user = message.author.display_name
        if unuser:
            msg = await message.channel.send("正在清空 Firebase Log 紀錄...")
            success = await delete_firebase_logs_async()
            if success:
                await msg.edit(content="🧹 Firebase Log 已成功清空！")
                # 【Firebase Log】清空舊紀錄後寫入這一條全新紀錄
                await push_firebase_log(
                    "SYSTEM", "Log 已被管理員手動清空", {"user": m_user}
                )
            else:
                await msg.edit(content="❌ 清空失敗，請檢查 Firebase 連線！")
        else:
            await message.channel.send("你沒有權限刪除 Log 喔，哈哈！")
            await push_firebase_log(
                "SECURITY", f"用戶 {m_user} 試圖清空 Log（無權限）"
            )
        return

    # ==================== 8. 一般 AI 對話與圖片對答 ====================
    if bot_c or message.content.startswith("!"):
        """
        if len(chat.get_history()) > 20:
            history = chat.get_history()[-20:]
            chat = client_chat.chats.create(
                model=model,
                config=types.GenerateContentConfig(system_instruction=ai_instruction),
                history=history
        )
        """
        txt = (
            message.content.replace("!", "", 1)
            if message.content.startswith("!")
            else message.content
        )
        ai_image = ""
        show_image = ""
        user_id = message.author.id

        if user_id == op_id:
            show_name = "Bally"
            tag = USER_TAGS["bally"]
        elif user_id == test_id:
            show_name = "Ethan"
            tag = USER_TAGS["ethan"]
        elif user_id == g_id:
            show_name = "George"
            tag = USER_TAGS["george"]
        elif user_id == j_id:
            show_name = "Jimmy"
            tag = USER_TAGS["jimmy"]
        else:
            show_name = "Other"
            tag = USER_TAGS["other"]

        async with message.channel.typing():
            image_description = ""

            # 檢查圖片附件
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
                                    ai_image = f"IMAGE:BackstageIdentification本訊息含有圖片\n{image_description}"
                                    show_image = f"圖片：\n{image_description}"
                        except Exception as e:
                            print(f"❌ 圖片處理失敗: {e}")
                            image_description += "\nBackstageIdentification[圖片讀取失敗]\n"

            ai_txt = f"Time:{current_time} USER:{tag} TXT:{txt} {image_description}"
            clean_txt = txt.replace("\n", " ")
            show_txt = f"時間：{current_time}  用戶：{show_name}  內容：{clean_txt}  {show_image}"

            response = chat.send_message(ai_txt)
            await message.channel.send(content=response.text)

            print("=" * 50)
            print(show_txt)
            clean_resp = response.text.replace("\n", " ")
            print(f"已回復({clean_resp})")

            # 【Firebase Log】對話紀錄上傳
            await push_firebase_log(
                "CHAT",
                f"收到來自 {message.author.display_name} ({show_name}) 的訊息",
                {
                    "user_id": str(user_id),
                    "user_tag": tag,
                    "prompt": txt,
                    "has_image": bool(image_description),
                    "bot_response": response.text,
                },
            )


# ==================== 背景 Dummy Web Server ====================
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()


threading.Thread(target=run_dummy_server, daemon=True).start()

bot.run(bot_token)
