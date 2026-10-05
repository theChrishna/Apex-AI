import requests
import time
import random

PRODUCTPAGE_URL = "http://localhost:9080/productpage"

if __name__ == "__main__":
    print("Generating traffic. Press Ctrl+C to stop.")
    try:
        while True:
            try:
                response = requests.get(PRODUCTPAGE_URL, timeout=5)
                print(f"Hit productpage — status {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"Request failed: {e}")

            time.sleep(random.uniform(2, 5))
    except KeyboardInterrupt:
        print("\nStopped by user.")