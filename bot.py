"""
VK -> Telegram форвардер сообщений.

Принимает вебхуки от VK Callback API (message_new) и пересылает
текст + вложения (фото, документы, стикеры, голосовые, видео)
в указанный чат Telegram.

Запуск:
    python bot.py

Требует переменные окружения (см. .env.example):
    VK_CONFIRMATION_CODE - код подтверждения из настроек Callback API
    VK_SECRET_KEY        - секретный ключ 
    VK_GROUP_ID           - id сообщества 
    TG_BOT_TOKEN          - токен Telegram-бота
    TG_CHAT_ID            - ваш chat_id в Telegram
"""

import os
import logging
import requests
from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("vk2tg")

app = Flask(__name__)


VK_CONFIRMATION_CODE = os.environ.get("VK_CONFIRMATION_CODE", "")
VK_SECRET_KEY = os.environ.get("VK_SECRET_KEY", "")
VK_GROUP_ID = os.environ.get("VK_GROUP_ID", "")

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

TG_API = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"


def tg_send_text(text: str, reply_to: str = None):
    if not text:
        return
    payload = {"chat_id": TG_CHAT_ID, "text": text}
    r = requests.post(f"{TG_API}/sendMessage", data=payload, timeout=15)
    if not r.ok:
        log.error("Ошибка sendMessage: %s", r.text)


def tg_send_photo(photo_url: str, caption: str = ""):
    payload = {"chat_id": TG_CHAT_ID, "photo": photo_url, "caption": caption[:1024]}
    r = requests.post(f"{TG_API}/sendPhoto", data=payload, timeout=30)
    if not r.ok:
        log.error("Ошибка sendPhoto: %s", r.text)
        tg_send_text(f"[фото] {photo_url}\n{caption}")


def tg_send_document(doc_url: str, caption: str = ""):
    payload = {"chat_id": TG_CHAT_ID, "document": doc_url, "caption": caption[:1024]}
    r = requests.post(f"{TG_API}/sendDocument", data=payload, timeout=30)
    if not r.ok:
        log.error("Ошибка sendDocument: %s", r.text)
        tg_send_text(f"[файл] {doc_url}\n{caption}")


def tg_send_audio(url: str, caption: str = ""):
    payload = {"chat_id": TG_CHAT_ID, "audio": url, "caption": caption[:1024]}
    r = requests.post(f"{TG_API}/sendAudio", data=payload, timeout=30)
    if not r.ok:
        log.error("Ошибка sendAudio: %s", r.text)
        tg_send_text(f"[аудио] {url}\n{caption}")


def tg_send_sticker(url: str):
    payload = {"chat_id": TG_CHAT_ID, "sticker": url}
    r = requests.post(f"{TG_API}/sendSticker", data=payload, timeout=15)
    if not r.ok:
        # пробуем как фото
        tg_send_photo(url, "[стикер]")


def best_photo_url(photo_obj: dict) -> str:
    sizes = photo_obj.get("sizes", [])
    if not sizes:
        return ""
    return max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))["url"]


def process_attachments(attachments: list, caption_text: str):
    caption_used = False

    for att in attachments:
        a_type = att.get("type")
        data = att.get(a_type, {})

        if a_type == "photo":
            url = best_photo_url(data)
            if url:
                tg_send_photo(url, caption_text if not caption_used else "")
                caption_used = True

        elif a_type == "doc":
            url = data.get("url", "")
            title = data.get("title", "файл")
            if url:
                tg_send_document(url, caption_text if not caption_used else title)
                caption_used = True

        elif a_type == "audio_message":
            url = data.get("link_mp3") or data.get("link_ogg", "")
            if url:
                tg_send_audio(url, "[голосовое]")

        elif a_type == "sticker":
            images = data.get("images", [])
            if images:
                url = max(images, key=lambda s: s.get("width", 0))["url"]
                tg_send_sticker(url)

        elif a_type == "video":
            owner_id = data.get("owner_id")
            video_id = data.get("id")
            access_key = data.get("access_key", "")
            title = data.get("title", "видео")
            link = f"https://vk.com/video{owner_id}_{video_id}"
            if access_key:
                link += f"_{access_key}"
            tg_send_text(f"[видео] {title}\n{link}")

        elif a_type == "wall":
            tg_send_text(f"[запись со стены] https://vk.com/wall{data.get('to_id')}_{data.get('id')}")

        elif a_type == "link":
            url = data.get("url", "")
            title = data.get("title", "")
            tg_send_text(f"[ссылка] {title}\n{url}")

        else:
            tg_send_text(f"[вложение типа {a_type}, не поддерживается напрямую]")

    return caption_used


def handle_message_new(obj: dict):
    message = obj.get("message", obj)  

    text = message.get("text", "") or ""
    attachments = message.get("attachments", []) or []

    from_id = message.get("from_id", "неизвестно")

    if attachments:
        prefix = f"Сообщение от {from_id}:\n{text}" if text else ""
        caption_used = process_attachments(attachments, prefix)
        if text and not caption_used:
            tg_send_text(f"Сообщение от {from_id}:\n{text}")
    elif text:
        tg_send_text(f"Сообщение от {from_id}:\n{text}")


@app.route("/vk-callback", methods=["POST"])
def vk_callback():
    data = request.get_json(force=True, silent=True) or {}


    if VK_SECRET_KEY and data.get("secret") != VK_SECRET_KEY:
        log.warning("Неверный secret key в запросе")
        return "ok"  

    if VK_GROUP_ID and str(data.get("group_id")) != str(VK_GROUP_ID):
        return "ok"

    event_type = data.get("type")

    if event_type == "confirmation":
        return VK_CONFIRMATION_CODE

    if event_type == "message_new":
        try:
            handle_message_new(data.get("object", {}))
        except Exception:
            log.exception("Ошибка обработки message_new")
        return "ok"

    return "ok"


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "service": "vk2tg forwarder"})


if __name__ == "__main__":
    missing = [k for k in ("TG_BOT_TOKEN", "TG_CHAT_ID", "VK_CONFIRMATION_CODE") if not os.environ.get(k)]
    if missing:
        log.warning("Не заданы переменные окружения: %s", ", ".join(missing))
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
