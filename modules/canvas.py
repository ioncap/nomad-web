import json
import re

import requests as req
from config import LLAMA_URL
from modules.helpers import sse
from modules.llm import stream_llm_canvas

PATCH_SYSTEM = """You are a precise text editor. Given a document and an edit instruction, output ONLY a JSON array of patch operations. No explanation, no markdown, just the JSON array.

Each operation must be one of:
{"op":"replace","old":"exact text to find","new":"replacement text"}
{"op":"delete","text":"exact text to remove"}
{"op":"insert_after","after":"text to find","new":"text to insert after it"}
{"op":"insert_before","before":"text to find","new":"text to insert before it"}
{"op":"append","new":"text to add at end"}

Rules:
- "old", "text", "after", "before" must be exact verbatim substrings from the document
- Keep each change minimal — only touch what needs changing
- Use multiple ops if needed
- Output ONLY the JSON array, nothing else"""

CANVAS_EDIT_PATTERNS = re.compile(
    r"\b(fix|rewrit|improv|updat|edit|refactor|clean|optimis|optimiz|extend|"
    r"translat|simplif|\badd\b|remov|delet|chang|modif|correct|format|renam|"
    r"replac|insert|append|overschrij|herschrij|verbeter|aanpass|"
    r"voeg\s+\w+\s+toe|verwijder|vertaal|vereenvoudig|verander|wijzig|"
    r"schrijf|genereer|zet\s+om|converteer)",
    re.IGNORECASE,
)


def is_small_edit(question, canvas):
    if not canvas:
        return False
    if len(canvas) < 200 or len(canvas) > 6000:
        return False
    q = question.lower()
    big_ops = [
        "rewrite", "herschrij", "overschrij", "translate", "vertaal", "format",
        "restructure", "simplify", "vereenvoudig", "converteer", "zet om",
    ]
    if any(w in q for w in big_ops):
        return False
    small_ops = [
        "fix", "correct", "rename", "change", "update", "add", "remove", "delete",
        "insert", "replace", "typo", "bug", "error",
        "verander", "wijzig", "voeg toe", "verwijder", "verbeter de",
        "functie", "regel", "variabele",
    ]
    return any(w in q for w in small_ops)


def is_canvas_edit_intent(question, canvas):
    if not canvas or not canvas.strip():
        return False
    return bool(CANVAS_EDIT_PATTERNS.search(question))


def guess_filename(canvas_content, hint=""):
    c = (hint + canvas_content).lower()
    if "def " in c or "import " in c or c.strip().startswith("#!"):
        return "script.py"
    if "function" in c or "const " in c or "let " in c or "=>" in c:
        return "script.js"
    if "<!doctype" in c or "<html" in c:
        return "index.html"
    if "#!/bin/bash" in c or "#!/bin/sh" in c:
        return "script.sh"
    return "document.md"


def build_canvas_context(canvas_content):
    if not canvas_content or not canvas_content.strip():
        return None
    return (
        "The user has a document open in the canvas:\n"
        "```\n"
        + canvas_content.strip()[:4000]
        + "\n```\n"
        "You can read and reference this document. "
        "If the user asks you to edit, fix, improve, update, rewrite or otherwise change the canvas, "
        "respond with a brief acknowledgement in chat AND use [CANVAS_UPDATE filename.ext] on its own line, "
        "followed by the complete updated content, then [/CANVAS_UPDATE] on its own line. "
        "Choose an appropriate filename extension (e.g. .py .js .md .sh .html). "
        "Do NOT include the [CANVAS_UPDATE] block in your chat response."
    )


def detect_canvas_update(text):
    pattern = r"\[CANVAS_UPDATE(?:\s+([^\]]+))?\]([\s\S]*?)\[/CANVAS_UPDATE\]"
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return text, None, None
    filename      = (m.group(1) or "").strip() or "updated"
    canvas_content = m.group(2).strip()
    rest           = text[m.end():].strip()
    chat_text      = text[: m.start()].strip() + ("\n\n" + rest if rest else "")
    return chat_text.strip(), canvas_content, filename


def canvas_edit_gen(question, canvas):
    fn = guess_filename(canvas or "", question)

    if is_small_edit(question, canvas):
        yield sse("search_status", message="Generating patch...")
        try:
            doc = (canvas or "")[:5000]
            r = req.post(
                LLAMA_URL + "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": PATCH_SYSTEM},
                        {
                            "role": "user",
                            "content": "Document:\n```\n" + doc + "\n```\n\nInstruction: " + question + "\n\nJSON array of ops:",
                        },
                    ],
                    "max_tokens": 1200,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=60,
            )
            raw = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
            ops = json.loads(raw)
            if not isinstance(ops, list):
                raise ValueError("not a list")
            valid = [op for op in ops if isinstance(op, dict) and "op" in op]
            if not valid:
                raise ValueError("empty ops")
            yield sse("canvas_patches", ops=valid)
            n = len(valid)
            yield sse("token", token="\u2713 " + str(n) + " change" + ("s" if n != 1 else "") + " ready \u2014 review in the diff tab.")
            yield sse("done")
            return
        except Exception:
            yield sse("search_status", message="Patch failed, rewriting...")

    yield sse("search_status", message="Rewriting canvas...")
    sys_prompt = (
        "You are a precise code and text editor. "
        "Output ONLY the complete updated document \u2014 no explanation, no preamble, "
        "no markdown fences unless the document itself uses them."
    )
    msgs = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": "Document:\n```\n" + (canvas or "") + "\n```\n\nInstruction: " + question + "\n\nOutput the complete updated document now:",
        },
    ]
    yield sse("canvas_start", filename=fn)
    yield from stream_llm_canvas(msgs, max_tokens=3000)
    yield sse("canvas_done", filename=fn)
    yield sse("token", token="\u2713 Canvas updated.")
    yield sse("done")
