import argparse
import json
import os
import urllib.error
import urllib.request


def send_discord(message: str) -> bool:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        print("[notify] DISCORD_WEBHOOK_URL is not configured")
        return False

    payload = {
        "content": message,
        "username": "FoxForge",
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
    except urllib.error.URLError as exc:
        print(f"[notify] Discord connection error: {exc.reason}")

    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--message",
        required=True,
        help="Message to send to Discord",
    )
    args = parser.parse_args()

    if send_discord(args.message):
        print("Discord notification sent")
        raise SystemExit(0)

    print("Discord notification failed")
    raise SystemExit(1)


if __name__ == "__main__":
    main()