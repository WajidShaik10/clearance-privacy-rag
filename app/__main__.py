"""Start the chat app: python -m app  (then open http://127.0.0.1:8000)."""

import os

import uvicorn

if __name__ == "__main__":
    # 127.0.0.1 = this computer only; nothing is reachable from the network.
    # Inside Docker it must listen on 0.0.0.0, and docker compose publishes it to
    # 127.0.0.1 on the host, so it is still only reachable from this computer.
    uvicorn.run("app.api:app", host=os.environ.get("HOST", "127.0.0.1"), port=8000)
