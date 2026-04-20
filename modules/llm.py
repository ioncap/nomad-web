import json

import requests as req
from config import LLAMA_URL, HELPER_URL, HELPER_MODEL
from modules.helpers import sse

# Phrase lengths (chars) and how many repetitions trigger a loop cut.
_LOOP_CHECKS = [(20, 3), (40, 3), (80, 2)]
_LOOP_WINDOW = 600  # only inspect the last N chars


def _is_looping(text: str) -> bool:
    """Return True when a repeated phrase is detected near the end of text."""
    if len(text) < 80:
        return False
    tail = text[-_LOOP_WINDOW:]
    for phrase_len, threshold in _LOOP_CHECKS:
        if len(tail) < phrase_len * threshold:
            continue
        phrase = tail[-phrase_len:]
        # count non-overlapping occurrences *before* the last instance
        if tail[: -phrase_len].count(phrase) >= threshold - 1:
            return True
    return False


def _llm_params(max_tokens: int) -> dict:
    return {
        "max_tokens": max_tokens,
        "stream": True,
        "frequency_penalty": 0.15,  # discourages token-level repetition
        "chat_template_kwargs": {"enable_thinking": False},
    }


def stream_llm(msgs, max_tokens=3000):
    try:
        r = req.post(
            LLAMA_URL + "/v1/chat/completions",
            json={"messages": msgs, **_llm_params(max_tokens)},
            stream=True,
            timeout=120,
        )
        buf = ""
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
                        buf += tk
                        yield sse("token", token=tk)
                        if _is_looping(buf):
                            yield sse("token", token="\n\n*(response cut: herhaling gedetecteerd)*")
                            return
                except Exception:
                    pass
    except Exception as e:
        yield sse("error", message="LLM: " + str(e))


def stream_llm_canvas(msgs, max_tokens=3000):
    """Stream LLM tokens destined for the canvas."""
    try:
        r = req.post(
            LLAMA_URL + "/v1/chat/completions",
            json={"messages": msgs, **_llm_params(max_tokens)},
            stream=True,
            timeout=120,
        )
        buf = ""
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
                        buf += tk
                        yield sse("canvas_token", token=tk)
                        if _is_looping(buf):
                            return  # silently cut canvas stream; content already written
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
