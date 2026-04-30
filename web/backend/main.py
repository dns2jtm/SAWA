from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import asyncio

app = FastAPI(title="FTMO Organism API")

# Allow CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.latest_state: Dict[str, Any] = {
            "equity": 0,
            "drawdown": 0.0,
            "volatility": 0.0,
            "last_action": "WAITING"
        }

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send latest state immediately upon connection
        await websocket.send_json(self.latest_state)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        self.latest_state.update(message)
        for connection in self.active_connections:
            try:
                await connection.send_json(self.latest_state)
            except Exception:
                pass

manager = ConnectionManager()

@app.websocket("/ws/organism")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection open, wait for client messages if any
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@app.post("/api/organism/push")
async def push_organism_state(state: dict):
    """
    Called by execution/live.py whenever the agent takes an action or equity changes.
    """
    await manager.broadcast(state)
    return {"status": "ok"}

@app.get("/api/debug/state")
async def debug_state():
    """Healthcheck endpoint"""
    return manager.latest_state
