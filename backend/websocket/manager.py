"""
WebSocket Connection Manager
=============================
Manages WebSocket connections for:
  - Gateway interface (999 call center)
  - Command Center dashboard
  - Field Team Portal (per-team connections)
"""
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("ws_manager")


class ConnectionManager:
    def __init__(self):
        self.gateway_connections: Set[WebSocket] = set()
        self.command_connections: Set[WebSocket] = set()
        self.field_connections: Dict[str, WebSocket] = {}  # team_id → ws

    # ------------------------------------------------------------------
    # Connect / Disconnect
    # ------------------------------------------------------------------
    async def connect_gateway(self, ws: WebSocket):
        await ws.accept()
        self.gateway_connections.add(ws)
        logger.info("Gateway client connected (%d total)", len(self.gateway_connections))

    async def connect_command(self, ws: WebSocket):
        await ws.accept()
        self.command_connections.add(ws)
        logger.info("Command center client connected (%d total)", len(self.command_connections))

    async def connect_field(self, team_id: str, ws: WebSocket):
        await ws.accept()
        self.field_connections[team_id] = ws
        logger.info("Field team '%s' connected (%d total field connections)", team_id, len(self.field_connections))

    def disconnect_gateway(self, ws: WebSocket):
        self.gateway_connections.discard(ws)
        logger.info("Gateway client disconnected (%d remaining)", len(self.gateway_connections))

    def disconnect_command(self, ws: WebSocket):
        self.command_connections.discard(ws)
        logger.info("Command client disconnected (%d remaining)", len(self.command_connections))

    def disconnect_field(self, team_id: str):
        self.field_connections.pop(team_id, None)
        logger.info("Field team '%s' disconnected (%d remaining)", team_id, len(self.field_connections))

    # ------------------------------------------------------------------
    # Broadcast / Send
    # ------------------------------------------------------------------
    async def broadcast_to_gateway(self, message: dict):
        dead = set()
        sent = 0
        for ws in self.gateway_connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as e:
                logger.warning("Gateway send failed: %s", e)
                dead.add(ws)
        self.gateway_connections -= dead
        if sent > 0 or dead:
            logger.info("broadcast_to_gateway: sent=%d, dead=%d, type=%s", sent, len(dead), message.get("type"))

    async def broadcast_to_command(self, message: dict):
        dead = set()
        sent = 0
        for ws in self.command_connections:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception as e:
                logger.warning("Command send failed: %s", e)
                dead.add(ws)
        self.command_connections -= dead

    async def send_to_team(self, team_id: str, message: dict):
        ws = self.field_connections.get(team_id)
        if ws:
            try:
                await ws.send_json(message)
                logger.info("Sent %s to team %s successfully", message.get("type"), team_id)
            except Exception as e:
                logger.warning("Field send to %s failed: %s", team_id, e)
                del self.field_connections[team_id]
        else:
            logger.warning(
                "send_to_team: team_id=%s NOT connected. Connected teams: %s",
                team_id, list(self.field_connections.keys()),
            )

    async def broadcast_to_all_teams(self, message: dict):
        dead = []
        for tid, ws in self.field_connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(tid)
        for tid in dead:
            self.field_connections.pop(tid, None)


# Singleton
manager = ConnectionManager()
