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
from modules.tool_registry import ToolRegistry

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
            m      = MACHINE_MAP[machine]
            # Use list form so local shell never parses the command —
            # single-quoted docker format strings etc. arrive intact.
            result = sp.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 f"{m['user']}@{m['host']}", command],
                capture_output=True, text=True, timeout=15,
            )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += "\nSTDERR: " + result.stderr.strip()
        return output[:2000] if output else "(no output)"
    except Exception as e:
        return f"Command error: {e}"


def agent_network_scan(args=None):
    """Fast network discovery: ARP cache → arp-scan → nmap → parallel Python pings."""
    import socket
    import subprocess as sp
    from concurrent.futures import ThreadPoolExecutor, wait as fut_wait
    import ipaddress

    if args is None:
        args = {}
    subnet  = args.get("subnet", "192.168.2.0/24")
    workers = int(args.get("workers", 32))
    timeout = int(args.get("timeout", 1))

    parts = []

    # 1. ARP cache (instant, always try)
    try:
        r = sp.run("arp -a", shell=True, capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            parts.append("ARP cache:\n" + r.stdout.strip())
    except Exception:
        pass

    # 2. arp-scan — hardware-level, most reliable (needs root on some systems)
    try:
        if sp.run(["which", "arp-scan"], capture_output=True, timeout=3).returncode == 0:
            r = sp.run(["arp-scan", "--localnet"],
                       capture_output=True, text=True, timeout=15)
            lines = [l for l in r.stdout.splitlines() if l and l[0].isdigit()]
            if lines:
                parts.append("arp-scan:\n" + "\n".join(lines))
                return "\n\n".join(parts)
    except Exception:
        pass

    # 3. nmap ping sweep (fast with --min-rate, no root needed)
    try:
        if sp.run(["which", "nmap"], capture_output=True, timeout=3).returncode == 0:
            r = sp.run(
                ["nmap", "-sn", "--min-rate", "300", subnet],
                capture_output=True, text=True, timeout=25,
            )
            hits = [l for l in r.stdout.splitlines() if "report" in l or "MAC" in l]
            if hits:
                parts.append("nmap ping sweep:\n" + "\n".join(hits))
                return "\n\n".join(parts)
    except Exception:
        pass

    # 4. Pure Python parallel ping sweep (stdlib, no external deps)
    try:
        network = ipaddress.ip_network(subnet, strict=False)
        hosts   = [str(h) for h in network.hosts()]

        # Always include known machine IPs so they're never missed
        for v in MACHINE_MAP.values():
            h = v["host"]
            if h not in ("localhost", "127.0.0.1") and h not in hosts:
                hosts.append(h)

        def _ping(host: str):
            try:
                r = sp.run(
                    ["ping", "-c", "1", "-W", str(timeout), host],
                    capture_output=True, timeout=timeout + 2,
                )
                if r.returncode != 0:
                    return None
                try:
                    name = socket.gethostbyaddr(host)[0]
                    return f"{host}  ({name})"
                except Exception:
                    return host
            except Exception:
                return None

        active = []
        with ThreadPoolExecutor(max_workers=min(workers, len(hosts))) as ex:
            futures = {ex.submit(_ping, h): h for h in hosts}
            done, _ = fut_wait(futures, timeout=min(workers * (timeout + 2), 30))
            for fut in done:
                try:
                    v = fut.result()
                    if v:
                        active.append(v)
                except Exception:
                    pass

        if active:
            try:
                active.sort(key=lambda s: [int(p) for p in s.split()[0].split(".")])
            except Exception:
                active.sort()
            parts.append(
                f"Ping sweep ({subnet}, {len(active)}/{len(hosts)} hosts):\n"
                + "\n".join(f"  {h}" for h in active)
            )
        else:
            parts.append(f"No hosts responded on {subnet}")
    except Exception as e:
        parts.append(f"Ping sweep error: {e}")

    return "\n\n".join(parts) if parts else "No devices found."


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


# ── Tool Registry ─────────────────────────────────────────────────────────────

registry = ToolRegistry()

def _r(name, func, desc, params=None, help_text="", example=""):
    """Register a tool. exec_timeout and open_in_new_tab are added automatically."""
    base = params or {}
    # exec_timeout: max wall-clock seconds the registry waits for this tool (default 60)
    # open_in_new_tab: if True the agent opens a new canvas tab instead of appending
    base.setdefault("exec_timeout", 60)
    base.setdefault("open_in_new_tab", False)
    registry.register(name, func, desc, base, help_text or desc, example)


_r("search_kb",
   lambda a: agent_search_kb(a.get("query", "")),
   "Semantic search in the local Qdrant knowledge base",
   help_text="Searches by vector similarity. Best for factual questions about saved topics.",
   example="zoek in de kennisbank naar Docker volumes")

_r("search_web",
   lambda a: agent_read_url("https://news.google.com/search?q=" + a.get("query", "").replace(" ", "+")),
   "Search the web via Google News RSS",
   help_text="Fetches Google News results. Good for current events and recent tech news.",
   example="zoek nieuws over Python 3.13")

_r("read_url",
   lambda a: agent_read_url(a.get("url", "")),
   "Fetch and extract readable text from any URL",
   help_text="Retrieves a page and strips HTML tags, scripts and styles. Returns up to 3000 characters.",
   example="lees de inhoud van https://docs.python.org")

_r("run_command",
   lambda a: agent_run_command(a.get("machine", "pi"), a.get("command", "")),
   "Run a whitelisted shell command on a machine via SSH",
   {"machine": "pi"},
   help_text=f"Allowed machines: pi, desktop, xps13.  Allowed commands (partial list): {', '.join(SAFE_COMMANDS[:14])}…",
   example="run df -h op de desktop")

_r("save_note",
   lambda a: agent_save_note(a.get("title", "Untitled"), a.get("content", "")),
   "Save a note to the knowledge base",
   help_text="Embeds and stores a note in Qdrant with source=agent_note. Skips exact duplicates.",
   example="sla een notitie op over SSH hardening tips")

_r("system_status",
   lambda a: agent_system_status(),
   "Pi + desktop + Qdrant health overview",
   help_text="Returns CPU, memory, disk and service stats for all known machines plus Qdrant vector count.",
   example="systeemstatus van alle machines")

_r("network_scan",
   agent_network_scan,
   "Fast network discovery: ARP cache → arp-scan → nmap → parallel ping",
   {"subnet": "192.168.2.0/24", "workers": 32, "timeout": 1, "exec_timeout": 45},
   help_text=(
       "Discovers live hosts using progressively slower methods:\n"
       "1. ARP cache (instant)\n"
       "2. arp-scan if installed (fast, hardware-level)\n"
       "3. nmap -sn if installed (~5 s)\n"
       "4. Pure Python ThreadPoolExecutor ping sweep (stdlib, ~2-5 s)\n\n"
       "workers = parallel ping threads (default 32).  "
       "timeout = per-host ping timeout (default 1 s).  "
       "exec_timeout = max wall-clock seconds the registry waits (default 45 s)."
   ),
   example="scan het lokale netwerk")

_r("network_scan_advanced",
   lambda a: agent_network_scan_advanced(a.get("subnet", "192.168.2.0/24")),
   "Nmap service version scan on the whole subnet",
   {"subnet": "192.168.2.0/24", "exec_timeout": 120},
   help_text="Runs nmap -sV --open. Shows open ports + service versions for every host. Takes 30-90 s.",
   example="scan het subnet op open services en versies")

_r("port_scan",
   lambda a: agent_port_scan(a.get("target", ""), a.get("ports", "top1000")),
   "Detailed port + service scan on one specific host",
   {"ports": "top1000", "exec_timeout": 90},
   help_text="nmap -sV on a single target. 'ports' can be 'top1000', '1-65535', or '22,80,443'.",
   example="scan de open poorten op 192.168.2.20")

_r("vuln_scan",
   lambda a: agent_vuln_scan(a.get("target", "")),
   "Nmap --script=vuln vulnerability scan on one host",
   {"exec_timeout": 180},
   help_text="Runs nmap --script=vuln. Can take 1-3 minutes. Only use on your own devices.",
   example="voer een vulnerability scan uit op 192.168.2.1")

_r("ping_host",
   lambda a: agent_ping_host(a.get("host", "")),
   "Ping a host (4 packets, 2 s timeout each)",
   help_text="Sends 4 ICMP packets and reports RTT statistics.",
   example="ping 192.168.2.1")

_r("kb_cleaner_status",
   lambda a: agent_kb_cleaner_status(),
   "KB Cleaner agent: running status, dry_run flag, last run statistics",
   help_text="Shows whether the background relevance cleaner is active, its interval, and stats from the last pass.",
   example="wat is de status van de KB cleaner?")

_r("kb_cleaner_run",
   lambda a: agent_kb_cleaner_run(a.get("dry_run", True)),
   "Trigger an immediate KB relevance clean pass",
   {"dry_run": True, "exec_timeout": 300},
   help_text="dry_run=true only logs what would be deleted.  dry_run=false deletes for real. Returns statistics.",
   example="voer een KB opschoning uit in dry-run modus")

_r("docker_status",
   lambda a: agent_docker_status(a.get("machine", "pi")),
   "Show running Docker containers on a machine",
   {"machine": "pi"},
   help_text="Runs 'docker ps' over SSH. machine = pi, desktop, or xps13.",
   example="welke Docker containers draaien op de desktop?")

_r("weather",
   lambda a: agent_weather(a.get("city", "Amsterdam")),
   "Current weather + 3-day forecast via Open-Meteo (no API key)",
   {"default_city": "Amsterdam"},
   help_text="Temperature, wind, precipitation and 3-day outlook from Open-Meteo's free API.",
   example="wat is het weer in Eindhoven?")

_r("dutch_temperatures",
   lambda a: agent_dutch_temperatures(),
   "Live temperatures for 8 Dutch cities",
   help_text="Amsterdam, Rotterdam, Utrecht, Den Haag, Eindhoven, Groningen, Maastricht, Leeuwarden.",
   example="temperaturen in Nederland")

_r("crypto",
   lambda a: agent_crypto_prices(),
   "BTC / ETH / SOL / ADA / DOGE prices in EUR and USD",
   help_text="Live prices + 24 h change from CoinGecko's free API.",
   example="wat zijn de actuele crypto-koersen?")

_r("exchange_rates",
   lambda a: agent_exchange_rates(a.get("base", "EUR")),
   "Exchange rates for major currencies",
   {"base": "EUR"},
   help_text="Fetches rates from open.er-api.com. 'base' can be any ISO 4217 code (EUR, USD, GBP, …).",
   example="wisselkoersen voor EUR naar USD")

_r("public_ip",
   lambda a: agent_public_ip(),
   "Public IP address with geolocation info",
   help_text="Uses ipinfo.io to get public IP, city, region, country and ISP.",
   example="wat is mijn publieke IP-adres?")

_r("hacker_news",
   lambda a: agent_hacker_news(),
   "Top 10 Hacker News stories with scores and URLs",
   help_text="Fetches top stories via the official HN Firebase API.",
   example="top Hacker News verhalen van vandaag")

_r("news_headlines",
   lambda a: agent_news_headlines(),
   "Latest BBC + Reuters headlines via RSS",
   help_text="Parses the BBC World and Reuters RSS feeds for the 10 most recent headlines.",
   example="laatste nieuws van BBC en Reuters")

_r("wikipedia",
   lambda a: agent_wikipedia(a.get("query", "")),
   "Wikipedia article summary (English)",
   help_text="Fetches the article extract. Falls back to a search result list if the exact title isn't found.",
   example="wikipedia artikel over containerisatie")

_r("list_tools",
   lambda a: agent_list_tools(),
   "Full catalog of all available agent tools",
   help_text="Returns name, description and enabled/disabled status for every registered tool.",
   example="wat kun je allemaal?")


def agent_list_tools() -> str:
    tools = registry.list_tools()
    lines = ["N.O.M.A.D Agent — available tools:\n"]
    for t in tools:
        status = "" if t["enabled"] else "  [DISABLED]"
        lines.append(f"  {t['name']:<24}  {t['description']}{status}")
    return "\n".join(lines)


# Backward-compat shim — code that still uses AGENT_TOOLS dict keeps working.
AGENT_TOOLS = {
    n: (lambda n: lambda a: registry.execute(n, a))(n)
    for n in registry._tools
}
