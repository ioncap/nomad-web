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

Call tools with JSON on its own line:
{"tool": "search_kb",             "args": {"query": "..."}}
{"tool": "search_web",            "args": {"query": "..."}}
{"tool": "read_url",              "args": {"url": "..."}}
{"tool": "run_command",           "args": {"machine": "pi|desktop|xps13", "command": "..."}}
{"tool": "save_note",             "args": {"title": "...", "content": "..."}}
{"tool": "system_status",         "args": {}}
{"tool": "network_scan",          "args": {}}
{"tool": "network_scan_advanced", "args": {"subnet": "192.168.2.0/24"}}
{"tool": "port_scan",             "args": {"target": "...", "ports": "top1000"}}
{"tool": "vuln_scan",             "args": {"target": "..."}}
{"tool": "ping_host",             "args": {"host": "..."}}
{"tool": "kb_cleaner_status",     "args": {}}
{"tool": "kb_cleaner_run",        "args": {"dry_run": true}}
{"tool": "docker_status",         "args": {"machine": "pi|desktop|xps13"}}
{"tool": "weather",               "args": {"city": "..."}}
{"tool": "dutch_temperatures",    "args": {}}
{"tool": "crypto",                "args": {}}
{"tool": "exchange_rates",        "args": {"base": "EUR"}}
{"tool": "public_ip",             "args": {}}
{"tool": "hacker_news",           "args": {}}
{"tool": "news_headlines",        "args": {}}
{"tool": "wikipedia",             "args": {"query": "..."}}
{"tool": "list_tools",            "args": {}}

Rules:
- One short line before each tool call explaining what you're doing
- After results: 2-3 sentence summary max
- Chain tools when needed
- Use list_tools to answer "what can you do?" questions"""

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


# ── Network: advanced & vuln scans ────────────────────────────────────────────

def agent_network_scan_advanced(subnet="192.168.2.0/24"):
    import subprocess as sp
    try:
        result = sp.run(
            f"nmap -sV --open {subnet} 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=120,
        )
        output = result.stdout.strip()
        return output[:4000] if output else "No open services found."
    except Exception as e:
        return f"Advanced scan error: {e}"


def agent_port_scan(target, ports="top1000"):
    import subprocess as sp
    if not target:
        return "Error: 'target' (IP or hostname) is required."
    port_arg = "--top-ports 1000" if ports == "top1000" else f"-p {ports}"
    try:
        result = sp.run(
            f"nmap -sV {port_arg} {target} 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=60,
        )
        return (result.stdout.strip() or "No results.")[:3000]
    except Exception as e:
        return f"Port scan error: {e}"


def agent_vuln_scan(target):
    import subprocess as sp
    if not target:
        return "Error: 'target' (IP or hostname) is required."
    try:
        result = sp.run(
            f"nmap --script=vuln {target} 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=180,
        )
        output = result.stdout.strip()
        return output[:4000] if output else "No vulnerabilities detected or nmap unavailable."
    except Exception as e:
        return f"Vuln scan error: {e}"


def agent_ping_host(host):
    import subprocess as sp
    if not host:
        return "Error: 'host' is required."
    try:
        result = sp.run(
            f"ping -c 4 -W 2 {host}",
            shell=True, capture_output=True, text=True, timeout=15,
        )
        return (result.stdout.strip() or result.stderr.strip() or "No output.")[:1000]
    except Exception as e:
        return f"Ping error: {e}"


# ── KB Cleaner control ────────────────────────────────────────────────────────

def agent_kb_cleaner_status():
    from modules.kb_cleaner import get_instance
    cleaner = get_instance()
    if not cleaner:
        return "KB Cleaner is not initialized."
    return json.dumps({
        "running":        cleaner.running,
        "dry_run":        cleaner.dry_run,
        "interval_hours": cleaner.interval // 3600,
        "last_run_stats": cleaner.last_stats,
    }, indent=2)


def agent_kb_cleaner_run(dry_run=True):
    from modules.kb_cleaner import get_instance
    cleaner = get_instance()
    if not cleaner:
        return "KB Cleaner is not initialized."
    original = cleaner.dry_run
    cleaner.dry_run = dry_run
    try:
        stats = cleaner.clean()
    finally:
        cleaner.dry_run = original
    return json.dumps(stats, indent=2)


# ── Extra API & system tools ──────────────────────────────────────────────────

def agent_hacker_news():
    try:
        top_ids = req.get(
            "https://hacker-news.firebaseio.com/v1/topstories.json",
            timeout=10,
        ).json()[:10]
        stories = []
        for sid in top_ids:
            s = req.get(
                f"https://hacker-news.firebaseio.com/v1/item/{sid}.json",
                timeout=5,
            ).json()
            url  = s.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            stories.append(f"  [{s.get('score', 0):>4}] {s.get('title', '?')}\n         {url}")
        return "Hacker News Top 10:\n" + "\n".join(stories)
    except Exception as e:
        return f"HN error: {e}"


def agent_docker_status(machine="pi"):
    cmd = "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'"
    return agent_run_command(machine, cmd)


# ── Self-documentation ────────────────────────────────────────────────────────

_TOOL_CATALOG = [
    ("search_kb",             '{"query": "..."}',                              "Semantic search in local Qdrant knowledge base"),
    ("search_web",            '{"query": "..."}',                              "Search via Google News RSS"),
    ("read_url",              '{"url": "..."}',                                "Fetch and extract text from any URL"),
    ("run_command",           '{"machine": "pi|desktop|xps13", "command":"…"}', "Run a whitelisted shell command on a machine"),
    ("save_note",             '{"title": "...", "content": "..."}',            "Save a note to the knowledge base"),
    ("system_status",         "{}",                                             "Pi + desktop + Qdrant health overview"),
    ("network_scan",          "{}",                                             "Fast ARP + ping sweep on 192.168.2.0/24"),
    ("network_scan_advanced", '{"subnet": "192.168.2.0/24"}',                  "Nmap service version scan on subnet"),
    ("port_scan",             '{"target": "...", "ports": "top1000"}',         "Detailed port + service scan on a specific host"),
    ("vuln_scan",             '{"target": "..."}',                             "Nmap --script=vuln vulnerability scan on a host"),
    ("ping_host",             '{"host": "..."}',                               "Ping a host (4 packets, 2s timeout)"),
    ("kb_cleaner_status",     "{}",                                             "Background KB cleaner: last stats, dry_run flag, interval"),
    ("kb_cleaner_run",        '{"dry_run": true}',                             "Trigger an immediate KB relevance clean pass"),
    ("docker_status",         '{"machine": "pi|desktop|xps13"}',               "Show running Docker containers on a machine"),
    ("weather",               '{"city": "..."}',                               "Current weather + 3-day forecast via Open-Meteo"),
    ("dutch_temperatures",    "{}",                                             "Live temperatures for 8 Dutch cities"),
    ("crypto",                "{}",                                             "BTC / ETH / SOL / ADA / DOGE in EUR + USD"),
    ("exchange_rates",        '{"base": "EUR"}',                               "Exchange rates for major world currencies"),
    ("public_ip",             "{}",                                             "Public IP address with geolocation"),
    ("hacker_news",           "{}",                                             "Top 10 Hacker News stories with scores"),
    ("news_headlines",        "{}",                                             "Latest BBC + Reuters headlines"),
    ("wikipedia",             '{"query": "..."}',                              "Wikipedia article summary"),
    ("list_tools",            "{}",                                             "This list — full catalog of available agent tools"),
]


def agent_list_tools():
    lines = ["N.O.M.A.D Agent — available tools:\n"]
    for name, args, desc in _TOOL_CATALOG:
        lines.append(f"  {name:<22}  {args:<44}  {desc}")
    return "\n".join(lines)


AGENT_TOOLS = {
    "search_kb":             lambda args: agent_search_kb(args.get("query", "")),
    "search_web":            lambda args: agent_read_url(f"https://news.google.com/search?q={args.get('query', '').replace(' ', '+')}"),
    "run_command":           lambda args: agent_run_command(args.get("machine", "pi"), args.get("command", "")),
    "network_scan":          lambda args: agent_network_scan(),
    "network_scan_advanced": lambda args: agent_network_scan_advanced(args.get("subnet", "192.168.2.0/24")),
    "port_scan":             lambda args: agent_port_scan(args.get("target", ""), args.get("ports", "top1000")),
    "vuln_scan":             lambda args: agent_vuln_scan(args.get("target", "")),
    "ping_host":             lambda args: agent_ping_host(args.get("host", "")),
    "system_status":         lambda args: agent_system_status(),
    "read_url":              lambda args: agent_read_url(args.get("url", "")),
    "save_note":             lambda args: agent_save_note(args.get("title", "Untitled"), args.get("content", "")),
    "kb_cleaner_status":     lambda args: agent_kb_cleaner_status(),
    "kb_cleaner_run":        lambda args: agent_kb_cleaner_run(args.get("dry_run", True)),
    "docker_status":         lambda args: agent_docker_status(args.get("machine", "pi")),
    "weather":               lambda args: agent_weather(args.get("city", "Amsterdam")),
    "dutch_temperatures":    lambda args: agent_dutch_temperatures(),
    "crypto":                lambda args: agent_crypto_prices(),
    "public_ip":             lambda args: agent_public_ip(),
    "hacker_news":           lambda args: agent_hacker_news(),
    "wikipedia":             lambda args: agent_wikipedia(args.get("query", "")),
    "exchange_rates":        lambda args: agent_exchange_rates(args.get("base", "EUR")),
    "news_headlines":        lambda args: agent_news_headlines(),
    "list_tools":            lambda args: agent_list_tools(),
}
