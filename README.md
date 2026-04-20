
# N.O.M.A.D Web

**N.O.M.A.D** (Networked Offline Machine Augmented Dialogue) is a fully local, privacy-first AI assistant web interface. It combines retrieval‑augmented generation (RAG), a powerful agent framework, voice interaction, and a collaborative **Canvas** where the LLM can read and edit documents in real time. This system now runs entirely on my own hardware – a Raspberry Pi 5, a desktop PC, and an XPS13 laptop – with no cloud dependencies.

> **Note:** This is a **hobby project** and not intended for production use. It was built as a personal experiment in local AI and home automation. The web interface and AI workflows are built around the knowledge base system originally created by **[ProjectNomad.us](https://projectnomad.us)**.

### Why Three Machines?
The setup is spread across three separate systems simply because **I had them lying around**. Running the full stack – LLM inference, vector database, embedding server, and web server – on a single device (especially a Raspberry Pi) would be **too heavy** and result in a sluggish experience. Distributing the load across a Pi 5, a desktop, and an XPS13 laptop keeps everything smooth and responsive while making good use of existing hardware.  
The project is **uploaded here so I can easily share it with friends**.

<img width="918" height="613" alt="image" src="https://github.com/user-attachments/assets/03f20a57-7e29-4415-ba80-e3914226d3a6" />
<img width="1095" height="785" alt="image" src="https://github.com/user-attachments/assets/1fce8845-cf73-425a-89b5-b4d2c596cd44" />

## ✨ Features

- **🗣️ Chat, RAG & Agent Modes** – Seamlessly switch between free conversation, knowledge‑base queries, and autonomous task execution.
- **📝 Collaborative Canvas** – A shared context window where the LLM can directly read, generate, and edit documents (code, markdown, text).
- **🔍 Local Knowledge Base** – Powered by Qdrant vector database and `nomic-embed-text` for semantic search.
- **🤖 LLM Integration** – Uses Qwen3‑4B (via `llama.cpp`) running on your desktop.
- **🎤 Voice Input / Output** – Speech‑to‑text via Whisper and text‑to‑speech via Piper.
- **📊 System Monitoring** – Live stats for all three machines (CPU, RAM, disk, containers) and service health.
- **🛠️ Extensible Agent Tools** – Includes web search, weather, crypto prices, command execution (sandboxed), and more.
- **🌙 Dark/Light Theme** – Toggleable UI theme with persistent preference.

## 🏗️ Architecture Overview

| Component            | Machine            | Description                                  |
|----------------------|--------------------|----------------------------------------------|
| **Flask Web App**    | Raspberry Pi 5      | Serves UI and API endpoints (`:5000`)        |
| **LLM (llama.cpp)**  | Desktop (`nomad.home`) | Qwen3‑4B inference (`:8081`)                |
| **Qdrant**           | Desktop            | Vector database for knowledge base (`:6333`) |
| **Whisper**          | Desktop            | Speech‑to‑text (`:8082`)                     |
| **Embedding Server** | XPS13              | `nomic-embed-text` via Ollama (`:11434`)     |
| **Voice Server**     | XPS13              | TTS proxy + voice chat (`:8085`)             |
| **Stats Servers**    | Pi, Desktop, XPS13 | System metrics (`:8083`)                     |

All inter‑service communication is over HTTP (with SSH fallback for XPS13 stats). The Pi acts as the central gateway and web server.

## 📋 Prerequisites

- **Hardware**: Three Linux machines (tested on Raspberry Pi 5, Ubuntu Desktop, Ubuntu XPS13)
- **Software**:
  - Python 3.10+
  - `llama.cpp` server running with a Qwen3‑4B GGUF model
  - Qdrant (Docker or native)
  - Ollama (on XPS13) with `nomic-embed-text` model
  - Whisper server (`faster-whisper`)
  - Piper TTS (optional, for local fallback)
  - Docker (optional, for Dozzle log viewer)

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/nomad-web.git
   cd nomad-web
   ```
    Create and activate a virtual environment
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    Install Python dependencies
    ```bash
    pip install -r requirements.txt
    ```
    Requirements include: Flask, requests, qdrant-client, python-dotenv, pdfminer.six (optional for PDF extraction)

    Set up environment variables
    Copy the example file and adjust to match your network setup:
    ```bash

    cp .env.example .env
    nano .env
    ```
    See Configuration for details.
```
    Prepare auxiliary services
    Start llama-server on the desktop.
    Ensure Qdrant is running and the collection nomad_knowledge_base exists.
    Run the embedding server on XPS13 (Ollama).
    (Optional) Start the stats servers on each machine. Configuration
```
All settings are managed via a .env file. Here are the most important variables:

Variable	Default	Description

NOMAD_HOST	nomad.home	Hostname of your desktop (LLM/Qdrant)

EMBED_URL	http://192.168.2.20:11434	Embedding server (XPS13)

LLAMA_URL	http://nomad.home:8081	llama.cpp inference endpoint

QDRANT_HOST	nomad.home	Qdrant host

QDRANT_PORT	6333	Qdrant port

WHISPER_URL	http://nomad.home:8082	Whisper STT endpoint

VOICE_URL	http://192.168.2.20:8085	Voice server for TTS/chat

SCORE_THRESHOLD	0.15	Minimum similarity for RAG results

MAX_HISTORY	20	Max conversation history kept

Refer to .env.example for the complete list.
🏃 Running the Application

Start the Flask development server (on the Raspberry Pi):
```bash

python nomad-web.py
```
The web interface will be available at http://raspberrypi.local:5000 (or your Pi's IP).

For production use, consider running behind a reverse proxy like Nginx with SSL (e.g., using Let's Encrypt).
🧭 Usage Guide
Modes

    RAG – Questions are first searched in your Qdrant knowledge base. The LLM answers using the retrieved context.

    Chat – Direct conversation with the LLM (canvas context is still included if open).

    Agent – The LLM can call external tools (weather, crypto, system commands, etc.) in a multi‑step loop.

Canvas

    Open the canvas with the 📄 button in the input bar.

    Write directly or ask the LLM to generate / edit content.

    Use Ctrl+S to download, Ctrl+F to find, Ctrl+Z for undo.

    Drag & drop files (text, code, PDF, images) onto the canvas.

    The canvas is always sent as context – the LLM sees what you see.

Voice

    Click the 🎤 button to record. Speech is transcribed via Whisper and sent as a message.

    TTS responses are proxied through the voice server.

System Dashboard

    Click system in the header to see real‑time stats from all three machines and service health.

📁 Project Structure
text
```
nomad-web/
├── nomad-web.py           # Main Flask application
├── .env.example           # Template for environment variables
├── requirements.txt       # Python dependencies
├── static/                # (Optional) Separate static assets
├── voice.html             # Standalone voice chat page
└── README.md
```
🔧 Extending
Adding a New Agent Tool

    Add the tool name and description to AGENT_SYSTEM.

    Implement the tool function (e.g., def agent_my_tool(args):).

    Register it in the AGENT_TOOLS dictionary.

Customizing the Knowledge Base

    Use the /save-to-kb endpoint programmatically, or let the LLM automatically suggest saving good Q&A pairs.

    Bulk import scripts can be written using the same embedding + Qdrant upsert pattern.

🤝 Contributing

This is a personal hobby project, but suggestions and bug reports are welcome. Please open an issue to discuss any proposed changes.
📜 License

This project is licensed under the MIT License – see the LICENSE file for details.
🙏 Acknowledgements

    ProjectNomad.us – The original inspiration and knowledge base system upon which this web interface is built.

    llama.cpp for efficient LLM inference.

    Qdrant for the vector database.

    Ollama for embeddings.

    Whisper for speech recognition.

    Piper for local TTS.

Built with ❤️ for local AI autonomy.
