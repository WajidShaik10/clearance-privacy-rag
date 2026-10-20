"""Start the chat app: python -m app  (then open http://127.0.0.1:8000)."""

import uvicorn

if __name__ == "__main__":
    # 127.0.0.1 = this computer only; nothing is reachable from the network.
    uvicorn.run("app.api:app", host="127.0.0.1", port=8000)
