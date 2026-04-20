import json

import requests as req
from config import LLAMA_URL, HELPER_URL, HELPER_MODEL
from modules.helpers import sse


def stream_llm(msgs, max_tokens=3000):
    try:
        r = req.post(
            LLAMA_URL + "/v1/chat/completions",
            json={
                "messages": msgs,
                "max_tokens": max_tokens,
                "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            stream=True,
            timeout=120,
        )
        for line in r.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    d  = json.loads(line)
                    tk = d.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if tk:
                        yield sse("token", token=tk)
                except Exception:
                    pass
    except Exception as e:
        yield sse("error", message="LLM: " + str(e))


def stream_llm_canvas(msgs, max_tokens=3000):
    """Stream LLM tokens destined for the canvas."""
    try:
        r = req.post(
            LLAMA_URL + "/v1/chat/completions",
            json={
                "messages": msgs,
                "max_tokens": max_tokens,
                "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            stream=True,
            timeout=120,
        )
        for line in r.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    d  = json.loads(line)
                    tk = d.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if tk:
                        yield sse("canvas_token", token=tk)
                except Exception:
                    pass
    except Exception as e:
        yield sse("error", message="LLM: " + str(e))


def helper_llm(messages, max_tokens=100):
    try:
        r = req.post(
            HELPER_URL + "/api/chat",
            json={
                "model": HELPER_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": max_tokens, "keep_alive": "60m"},
            },
            timeout=20,
        )
        return r.json().get("message", {}).get("content", "").strip()
    except Exception:
        return ""


def contextualize_question(question, history):
    if not history:
        return question
    recent = history[-6:]
    conv = ""
    for m in recent:
        role = "User" if m["role"] == "user" else "Assistant"
        conv += role + ": " + m["content"][:200] + "\n"
    rewritten = helper_llm(
        [
            {
                "role": "system",
                "content": (
                    "Given a conversation and a follow-up question, rewrite the "
                    "follow-up into a standalone question. Return ONLY the rewritten "
                    "question. If already standalone, return as-is."
                ),
            },
            {
                "role": "user",
                "content": "Conversation:\n" + conv + "\nFollow-up: " + question + "\nStandalone:",
            },
        ],
        max_tokens=100,
    )
    return rewritten if len(rewritten) > 5 else question
