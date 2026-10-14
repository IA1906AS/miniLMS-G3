import requests


def main():
    r = requests.get("https://pypi.org/pypi/uv/json", timeout=10)
    print("Phiên bản uv mới nhất trên PyPI:", r.json()["info"]["version"])


if __name__ == "__main__":
    main()
