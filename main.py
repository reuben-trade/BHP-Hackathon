from fastapi import FastAPI
app = FastAPI(
    title="BHP Mooring System Backend API",
    description="Backend API",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "BHP Mooring Backend API",
        "version": "1.0.0"
    }

@app.post("/receive/")
async def receive(input_json: dict):
    return input_json


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)