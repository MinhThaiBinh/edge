import uvicorn
import os

if __name__ == "__main__":
    # Ensure the project root is in PYTHONPATH
    os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
