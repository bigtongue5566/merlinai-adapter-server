"""Observed Merlin Web wire format; internal messages remain lossless."""

import re
import uuid

from fastapi import HTTPException

WEB_PATH = "/arcane/api/v2/thread/unified"
WEB_ORIGIN = "https://www.getmerlin.in"
WEB_VERSION = "web-merlin"
TRUNCATION_NOTICE = '*This response stopped at the maximum output length. Reply "continue" to pick up where it left off.*'


def _text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") not in {"text", "input_text"}:
                raise HTTPException(422, "Web transport currently supports text content only")
            text = item.get("text")
            if not isinstance(text, str):
                raise HTTPException(422, "Web transport requires string text parts")
            parts.append(text)
        return "".join(parts)
    raise HTTPException(422, "Unsupported Web message content")


def build_web_payload(payload):
    if payload.get("params", {}).get("tools"):
        raise HTTPException(422, "Web transport requires emulated tools")
    messages = payload["messages"]
    if len(messages) == 1 and messages[0]["role"] == "user":
        prompt = _text(messages[0].get("content"))
    else:
        prompt = "\n\n".join(message["role"].upper() + ":\n" + _text(message.get("content"))
                              for message in messages)
    return {
        "attachments": [], "chatId": str(uuid.uuid4()), "language": "AUTO",
        "message": {"childId": str(uuid.uuid4()), "content": prompt, "context": "",
                    "id": str(uuid.uuid4()), "parentId": "root"},
        "mode": "UNIFIED_CHAT", "model": payload["model"],
        "metadata": {"deepResearch": False, "merlinMagic": False, "noTask": True,
                     "proFinderMode": False, "mcpConfig": {"isEnabled": False},
                     "isWebpageChat": False, "webAccess": False},
    }


def remove_truncation_notice(text):
    return re.sub(r"\n\n" + re.escape(TRUNCATION_NOTICE) + r"[ \t\r\n]*$", "", text)
