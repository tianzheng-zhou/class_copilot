import uvicorn

if __name__ == "__main__":
    uvicorn.run("class_copilot.main:app", host="127.0.0.1", port=29038, workers=1, log_level="warning")
