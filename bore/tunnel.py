import requests

from .config import get_token


# API_URL = "http://127.0.0.1:8000"
API_URL = "https://api.borehook.com"


def start_tunnel(subdomain, port):

    token = get_token()
    print("TOKEN:", token)

    if not token:
        raise Exception(
            "Run: bore login"
        )

    response = requests.post(
        f"{API_URL}/api/tunnels/start/",
        json={
            "subdomain": subdomain,
            "port": port,
        },
        # headers={
        #     "Authorization": f"Bearer {token}"
        # },
        headers = {
              "Authorization": f"Token {token}"
   },
        timeout=30,
    )
    
    # print("STATUS:", response.status_code)
    # print("BODY:", response.text)

    response.raise_for_status()

    data = response.json()
    print(response.json())

    return data