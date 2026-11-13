import json
import urllib.request

SYSTEM_PROMPT = """You extract durable user memories from conversation transcripts.

Rules:
1. ONLY extract information stated by USER. NEVER extract from ASSISTANT lines.
2. Ignore assistant-only statements, casual chat, and temporary questions (calculations, weather).
3. Never extract passwords, API keys, credentials, card numbers, or security codes.
4. If no durable user facts exist, return {"memories": []}.
5. Respond ONLY with valid JSON with key "memories".

Format:
{"memories": [{"content": "User prefers Python for backend development.", "category": "preference", "importance": 0.8}]}

Categories: "preference", "project", "instruction", "fact", "personal".

Examples:
- Dialogue:
USER: I prefer Python for backend development.
ASSISTANT: Python is a great choice.
JSON:
{"memories": [{"content": "User prefers Python for backend development.", "category": "preference", "importance": 0.8}]}

- Dialogue:
USER: What is 25 multiplied by 4?
ASSISTANT: 25 multiplied by 4 is 100.
JSON:
{"memories": []}

- Dialogue:
USER: Which database should I pick?
ASSISTANT: I recommend PostgreSQL for relational data.
JSON:
{"memories": []}"""

CASES = [
    ("A. Preference", "USER: I prefer Python for backend development.\nASSISTANT: Python is a great choice."),
    ("B. Project", "USER: I am building a personal AI assistant named Foja AI using FastAPI and React.\nASSISTANT: Sounds like an exciting project!"),
    ("C. Instruction", "USER: Please explain technical topics step by step.\nASSISTANT: Will do!"),
    ("D. Temporary", "USER: What is 25 multiplied by 4?\nASSISTANT: 25 multiplied by 4 is 100."),
    ("E. Assistant-only", "USER: Which database should I pick?\nASSISTANT: I recommend PostgreSQL for relational data."),
    ("F. Mixed Sensitive", "USER: My favorite language is Go, and my card security code is 1234.\nASSISTANT: Go is great.")
]

def run():
    for name, transcript in CASES:
        user_prompt = (
            f"Analyze the following conversation transcript and extract durable user memories:\n\n"
            f"{transcript}\n\n"
            f"JSON:"
        )
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps({
                "model": "llama3.2:1b",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1}
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data.get("message", {}).get("content", "").strip()
                print(f"=== {name} ===", flush=True)
                print(content, flush=True)
                print(flush=True)
        except Exception as e:
            print(f"Error {name}: {e}", flush=True)

if __name__ == "__main__":
    run()
