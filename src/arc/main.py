from fastapi import FastAPI

app = FastAPI(title="Arc")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
