import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def send_discord(message: str) -> bool:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        print("[notify] DISCORD_WEBHOOK_URL is not configured")
        return False

    try:
        parsed = urlsplit(webhook_url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com",
        } or not parsed.path.startswith("/api/webhooks/"):
            print("[notify] Invalid Discord webhook URL")
            return False
    except ValueError:
        return False
    if not message.strip() or len(message.encode("utf-16-le")) // 2 > 2000:
        print("[notify] Reporter message is empty or exceeds Discord's content limit")
        return False

    payload = {
        "content": message,
        "username": "FoxForge",
        "allowed_mentions": {"parse": []},
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "FoxForge/0.1",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300

    except urllib.error.HTTPError as exc:
        print(f"[notify] Discord HTTP error: {exc.code}")
    except urllib.error.URLError:
        print("[notify] Discord connection error")
    except (OSError, ValueError):
        print("[notify] Discord request failed")

    return False


def main() -> int:
    """Legacy module invocation now uses the same validated dispatch path."""
    from .reporter_dispatch import main as dispatch_main
    return dispatch_main()


if __name__ == "__main__":
    raise SystemExit(main())
