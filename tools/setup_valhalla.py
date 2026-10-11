"""Wait for Valhalla to be ready and print its URL."""
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings


def main() -> None:
    settings = get_settings()
    url = settings.valhalla_url
    print(f"Waiting for Valhalla at {url}/status ...")

    import urllib.request
    import urllib.error

    for attempt in range(720):
        try:
            req = urllib.request.urlopen(f"{url}/status", timeout=5)
            if req.status == 200:
                print(f"\nValhalla is ready at {url}")
                print(f"Set VALHALLA_URL={url} in .env")
                return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        if attempt % 10 == 0:
            print(f"  attempt {attempt + 1}/120 ...")
        time.sleep(5)

    print("\nValhalla did not become ready within 60 minutes.")
    print("Check: docker compose logs valhalla")
    sys.exit(1)


if __name__ == "__main__":
    main()
