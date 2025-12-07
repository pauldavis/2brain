#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(
        description="Upload an export ZIP to the 2brain remote API."
    )
    parser.add_argument("file", type=Path, help="Path to the .zip export file.")
    parser.add_argument(
        "--url",
        default=os.environ.get("API_URL", "http://localhost:8100"),
        help="Base URL of the 2brain API (default: http://localhost:8100 or API_URL env var).",
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("ADMIN_API_KEY"),
        help="Admin API Key for authentication (default: ADMIN_API_KEY env var).",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "claude", "chatgpt"],
        default="auto",
        help="Source system type (default: auto).",
    )

    args = parser.parse_args()

    if not args.file.exists():
        print(f"Error: File '{args.file}' does not exist.")
        sys.exit(1)

    if not args.key:
        print("Error: API Key is required. Set ADMIN_API_KEY env var or use --key.")
        sys.exit(1)

    url = f"{args.url.rstrip('/')}/ingest/upload"
    headers = {"Authorization": f"Bearer {args.key}"}
    params = {"source": args.source}

    print(f"Uploading {args.file.name} to {url}...")

    try:
        with open(args.file, "rb") as f:
            files = {"file": (args.file.name, f, "application/zip")}
            response = requests.post(url, headers=headers, params=params, files=files)

        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('message', 'Upload accepted')}")
        else:
            print(f"Failed (HTTP {response.status_code}): {response.text}")
            sys.exit(1)

    except requests.RequestException as e:
        print(f"Network error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
