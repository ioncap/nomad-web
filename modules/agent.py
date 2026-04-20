import hashlib
import json
import os
import re
import time

import requests as req
from qdrant_client import QdrantClient, models

from config import COLLECTION, NOMAD_HOST, QDRANT_HOST, QDRANT_PORT, STATS_URL, XPS13_HOST
from modules.embeddings import get_embedding
from modules.helpers import get_pi_stats

AGENT_SYSTEM = """You are N.O.M.A.D Agent — direct, efficient, sharp. Complete tasks with minimal words.

Tools available (call with JSON on its own line):
{"tool": "search_kb", "args": {"query": "..."}}
{"tool": "search_web", "args": {"query": "..."}}
{"tool": "run_command", "args": {"machine": "pi|desktop|xps13", "command": "..."}}
{"tool": "save_note", "args": {"title": "...", "content": "..."}}
{"tool": "network_scan", "args": {}}
{"tool": "system_status", "args": {}}
{"tool": "read_url", "args": {"url": "..."}}
{"tool": "weather", "args": {"city": "..."}}
{"tool": "dutch_temperatures", "args": {}}
{"tool": "crypto", "args": {}}
{"tool": "public_ip", "args": {}}
{"tool": "wikipedia", "args": {"query": "..."}}
{"tool": "exchange_rates", "args": {"base": "EUR"}}
{"tool": "news_headlines", "args": {}}

Rules:
- One short line explaining what you're doing, then the JSON tool call
- After tool results: 2-3 sentence summary max
- Chain tools when needed"""

SAFE_COMMANDS = [
    "ls", "cat", "head", "tail", "grep", "find", "wc", "df", "free", "uptime",
    "hostname", "uname", "whoami", "date", "ps", "top", "ip", "ping", "nmap",
    "arp", "ss", "netstat", "curl", "wget", "docker", "systemctl", "journalctl",
    "sensors", "lsblk", "lscpu", "du", "file", "stat", "which", "echo", "sort",
    "uniq", "awk", "sed", "tr", "cut", "tee", "nproc", "lsusb", "lspci",
]

MACHINE_MAP = {
    "pi":      {"host": "localhost",    "user": "ioncap"},
    "desktop": {"host": "nomad.home",   "user": "ioncap"},
    "xps13":   {"host": "192.168.2.20", "user": "ioncap"},
}


def agent_search_kb(query):
    try:
        emb    = get_embedding(query)
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        results = client.query_points(collection_name=COLLECTION, query=emb, limit=5)
        output = []
        for r in results.points:
            pl = r.payload or {}
            output.append(
                f"[{pl.get('article_title', '?')}] (score:{r.score:.2f})\n{pl.get('content', '')[:300]}"
            )
        return "\n\n---\n".join(output) if output else "No results found."
    except Exception as e:
        return f"Search error: {e}"


def agent_run_command(machine, command):
    import subprocess as sp

    cmd_parts = command.strip().split()
    if not cmd_parts:
        return "Empty command"
    if cmd_parts[0] not in SAFE_COMMANDS:
        return f"Command '{cmd_parts[0]}' not allowed."
    machine = machine.lower().strip()
    if machine not in MACHINE_MAP:
        return f"Unknown machine: {machine}"
    try:
        if machine == "pi":
            result = sp.run(command, shell=True, capture_output=True, text=True, timeout=15)
        else:
            m       = MACHINE_MAP[machine]
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {m['user']}@{m['host']} '{command}'"
            result  = sp.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
        if result.stderr.strip():
            output += "\nSTDERR: " + result.stderr.strip()
        return output[:2000] if output else "(no output)"
    except Exception as e:
        return f"Command error: {e}"


def agent_network_scan():
    import subprocess as sp

    try:
        result = sp.run("arp -a", shell=True, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()
        nmap   = sp.run("which nmap", shell=True, capture_output=True, text=True)
        if nmap.returncode == 0:
            scan = sp.run(
                "nmap -sn 192.168.2.0/24 2>/dev/null | grep -E 'scan report|MAC'",
                shell=True, capture_output=True, text=True, timeout=30,
            )
            if scan.stdout.strip():
                output += "\n\nNmap:\n" + scan.stdout.strip()
        return output if output else "No devices found"
    except Exception as e:
        return f"Scan error: {e}"


def agent_system_status():
    stats = {}
    try:
        stats["pi"] = get_pi_stats()
    except Exception:
        stats["pi"] = {"error": "unavailable"}
    try:
        stats["desktop"] = req.get(f"{STATS_URL}/stats", timeout=5).json()
    except Exception:
        stats["desktop"] = {"error": "unavailable"}
    try:
        r = req.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION}", timeout=3)
        d = r.json()["result"]
        stats["qdrant"] = {"vectors": d["points_count"], "status": d["status"]}
    except Exception:
        stats["qdrant"] = {"error": "unavailable"}
    return json.dumps(stats, indent=2)


def agent_read_url(url):
    try:
        r    = req.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        text = re.sub(r"<script[^>]*>.*?</script>", "", r.text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>",   "", text,   flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000]
    except Exception as e:
        return f"Fetch error: {e}"


def agent_save_note(title, content):
    try:
        chunk  = f"Note: {title}\n{content}"
        emb    = get_embedding(chunk)
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        pid    = abs(int(hashlib.md5(chunk.encode()).hexdigest(), 16)) % (2 ** 63)
        client.upsert(
            collection_name=COLLECTION,
            points=[
                models.PointStruct(
                    id=pid,
                    vector=emb,
                    payload={
                        "source":        "agent_note",
                        "content_type":  "agent_note",
                        "article_title": title,
                        "content":       chunk,
                        "generated_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            ],
        )
        return f"Saved: {title}"
    except Exception as e:
        return f"Save error: {e}"


def agent_weather(city="Amsterdam"):
    codes = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 51: "Light drizzle", 61: "Slight rain", 63: "Rain",
        65: "Heavy rain", 80: "Showers", 95: "Thunderstorm",
    }
    try:
        geo = req.get(
            f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1",
            timeout=10,
        ).json()
        if not geo.get("results"):
            return f"City not found: {city}"
        r    = geo["results"][0]
        lat, lon, name, country = r["latitude"], r["longitude"], r["name"], r.get("country", "")
        w    = req.get(
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,apparent_temperature,precipitation"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
            f"&timezone=auto&forecast_days=3",
            timeout=10,
        ).json()
        cur   = w["current"]
        daily = w["daily"]
        desc  = codes.get(cur.get("weather_code", 0), "?")
        result = f"{name}, {country}: {desc}, {cur['temperature_2m']}°C (feels {cur['apparent_temperature']}°C), wind {cur['wind_speed_10m']} km/h\n"
        result += "Forecast:\n"
        for i in range(min(3, len(daily["time"]))):
            d_desc  = codes.get(daily["weather_code"][i], "?")
            result += f"  {daily['time'][i]}: {d_desc}, {daily['temperature_2m_min'][i]}-{daily['temperature_2m_max'][i]}°C\n"
        return result
    except Exception as e:
        return f"Weather error: {e}"


def agent_dutch_temperatures():
    cities = ["Amsterdam", "Rotterdam", "Utrecht", "Den Haag", "Eindhoven", "Groningen", "Maastricht", "Leeuwarden"]
    codes  = {0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️", 51: "🌦", 61: "🌧", 80: "🌦", 95: "⛈"}
    results = []
    for city in cities:
        try:
            geo = req.get(
                f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&country=NL",
                timeout=5,
            ).json()
            if geo.get("results"):
                lat, lon = geo["results"][0]["latitude"], geo["results"][0]["longitude"]
                w    = req.get(
                    f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code",
                    timeout=5,
                ).json()
                icon = codes.get(w["current"]["weather_code"], "?")
                results.append(f"  {icon} {city}: {w['current']['temperature_2m']}°C")
        except Exception:
            results.append(f"  ? {city}: unavailable")
    return "NL temperatures:\n" + "\n".join(results)


def agent_crypto_prices():
    try:
        r    = req.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,solana,cardano,dogecoin"
            "&vs_currencies=eur,usd&include_24hr_change=true",
            timeout=10,
        )
        data  = r.json()
        names = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA", "dogecoin": "DOGE"}
        result = "Crypto:\n"
        for coin, sym in names.items():
            if coin in data:
                d     = data[coin]
                ch    = d.get("eur_24h_change", 0)
                arrow = "↑" if ch > 0 else "↓"
                result += f"  {sym}: €{d.get('eur', 0):,.0f} / ${d.get('usd', 0):,.0f} ({arrow}{abs(ch):.1f}%)\n"
        return result
    except Exception as e:
        return f"Crypto error: {e}"


def agent_public_ip():
    try:
        d = req.get("https://ipinfo.io/json", timeout=10).json()
        return f"IP: {d.get('ip')} | {d.get('city')}, {d.get('region')}, {d.get('country')} | {d.get('org')}"
    except Exception as e:
        return f"IP error: {e}"


def agent_wikipedia(query):
    try:
        r = req.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}",
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json()
            return f"{d.get('title', '')}\n{d.get('extract', 'No content.')[:500]}"
        s = req.get(
            f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&format=json",
            timeout=10,
        ).json()
        if len(s) > 1 and s[1]:
            return "Results: " + ", ".join(s[1][:5])
        return f"Nothing found: {query}"
    except Exception as e:
        return f"Wikipedia error: {e}"


def agent_exchange_rates(base="EUR"):
    try:
        d = req.get(f"https://open.er-api.com/v6/latest/{base}", timeout=10).json()
        if d.get("result") == "success":
            rates     = d["rates"]
            important = ["USD", "GBP", "JPY", "CHF", "CAD", "AUD", "SEK", "NOK", "DKK", "PLN", "TRY"]
            result    = f"1 {base} =\n"
            for cur in important:
                if cur in rates:
                    result += f"  {cur}: {rates[cur]:.4f}\n"
            return result
        return "Exchange rate API error"
    except Exception as e:
        return f"Exchange error: {e}"


def agent_news_headlines():
    try:
        import feedparser
        headlines = []
        for name, url in [
            ("BBC",     "http://feeds.bbci.co.uk/news/rss.xml"),
            ("Reuters", "https://feeds.reuters.com/reuters/worldNews"),
        ]:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    headlines.append(f"[{name}] {entry.get('title', '?')}")
            except Exception:
                pass
        return "Headlines:\n" + "\n".join("  " + h for h in headlines[:10]) if headlines else "No headlines available"
    except Exception as e:
        return f"News error: {e}"


AGENT_TOOLS = {
    "search_kb":          lambda args: agent_search_kb(args.get("query", "")),
    "search_web":         lambda args: agent_read_url(f"https://news.google.com/search?q={args.get('query', '').replace(' ', '+')}"),
    "run_command":        lambda args: agent_run_command(args.get("machine", "pi"), args.get("command", "")),
    "network_scan":       lambda args: agent_network_scan(),
    "system_status":      lambda args: agent_system_status(),
    "read_url":           lambda args: agent_read_url(args.get("url", "")),
    "save_note":          lambda args: agent_save_note(args.get("title", "Untitled"), args.get("content", "")),
    "weather":            lambda args: agent_weather(args.get("city", "Amsterdam")),
    "dutch_temperatures": lambda args: agent_dutch_temperatures(),
    "crypto":             lambda args: agent_crypto_prices(),
    "public_ip":          lambda args: agent_public_ip(),
    "wikipedia":          lambda args: agent_wikipedia(args.get("query", "")),
    "exchange_rates":     lambda args: agent_exchange_rates(args.get("base", "EUR")),
    "news_headlines":     lambda args: agent_news_headlines(),
}
