#!/usr/bin/env python3
"""
Historical event backfill for Matrix Indexer.
"""
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

import pymongo
from nio import AsyncClient

from config import IndexerConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("matrix_backfill")


class MatrixBackfill:
    """Backfill historical Matrix events."""
    
    def __init__(self, config: IndexerConfig):
        self.config = config
        self.client: Optional[AsyncClient] = None
        self.mongo_client: Optional[pymongo.MongoClient] = None
        self.db = None
        self.events_collection = None
        
        log.setLevel(getattr(logging, config.log_level))
    
    async def connect(self) -> None:
        """Initialize connections."""
        log.info("Initializing backfill service")
        
        # Create Matrix client
        self.client = AsyncClient(
            self.config.matrix.homeserver,
            self.config.matrix.user_id,
            config={"client_max_workers": 4}
        )
        
        # Login
        if self.config.matrix.access_token:
            self.client.access_token = self.config.matrix.access_token
            log.info("Using access token")
        elif self.config.matrix.password:
            log.info("Logging in with password")
            resp = await self.client.login(
                self.config.matrix.password,
                device_name=self.config.matrix.device_name
            )
            if hasattr(resp, 'access_token'):
                self.config.matrix.access_token = resp.access_token
                log.info("Successfully logged in")
            else:
                raise RuntimeError(f"Login failed: {resp}")
        
        # Connect to MongoDB
        log.info("Connecting to MongoDB")
        self.mongo_client = pymongo.MongoClient(self.config.mongo.uri)
        self.db = self.mongo_client[self.config.mongo.db]
        self.events_collection = self.db[self.config.mongo.events_collection]
        
        log.info("Backfill service connected")
    
    async def backfill_room(self, room_id: str, limit: int = 1000) -> int:
        """Backfill historical events for a room."""
        log.info("Backfilling room %s (limit=%d)", room_id, limit)
        
        try:
            # Get room from client
            room = self.client.rooms.get(room_id)
            if not room:
                log.warning("Room %s not found in client", room_id)
                return 0
            
            # Get messages in batches
            event_count = 0
            start_token = room.prev_batch  # Start from earliest known token
            
            for i in range(0, limit, self.config.backfill_batch_size):
                if not start_token:
                    log.info("Reached beginning of room history")
                    break
                
                log.debug("Backfill batch %d for room %s", i // self.config.backfill_batch_size, room_id)
                
                resp = await self.client.room_messages(
                    room_id,
                    start=start_token,
                    direction="b",  # backwards
                    limit=self.config.backfill_batch_size
                )
                
                if not hasattr(resp, 'chunk') or not resp.chunk:
                    log.info("No more messages in room %s", room_id)
                    break
                
                # Store events
                docs_to_insert = []
                for event in resp.chunk:
                    if not hasattr(event, 'event_id') or not event.event_id:
                        continue
                    
                    doc = {
                        "event_id": event.event_id,
                        "room_id": room_id,
                        "sender": getattr(event, "sender", None),
                        "type": getattr(event, "type", None),
                        "origin_server_ts": getattr(event, "origin_server_ts", None),
                        "timestamp": int(getattr(event, "timestamp", 0)),
                        "source": getattr(event, "source", {}),
                        "content": getattr(event, "content", {}),
                        "backfilled": True,
                    }
                    docs_to_insert.append(doc)
                
                if docs_to_insert:
                    try:
                        for doc in docs_to_insert:
                            self.events_collection.replace_one(
                                {"event_id": doc["event_id"]},
                                doc,
                                upsert=True
                            )
                        event_count += len(docs_to_insert)
                        log.info("Stored %d events from backfill batch", len(docs_to_insert))
                    except Exception as e:
                        log.error("Error storing backfill events: %s", e)
                
                # Update start token for next batch
                if hasattr(resp, 'start'):
                    start_token = resp.start
                else:
                    break
                
                await asyncio.sleep(0.1)  # Rate limiting
            
            log.info("Backfilled %d total events for room %s", event_count, room_id)
            return event_count
        
        except Exception as e:
            log.error("Error backfilling room %s: %s", room_id, e, exc_info=True)
            return 0
    
    async def backfill_all_rooms(self) -> Dict[str, int]:
        """Backfill all joined rooms."""
        log.info("Starting backfill for all rooms")
        results = {}
        
        # Get all joined rooms
        rooms = list(self.client.rooms.keys())
        log.info("Found %d joined rooms", len(rooms))
        
        for room_id in rooms:
            count = await self.backfill_room(room_id)
            results[room_id] = count
            await asyncio.sleep(0.5)  # Avoid rate limiting
        
        log.info("Backfill complete. Total events: %d", sum(results.values()))
        return results
    
    async def stop(self) -> None:
        """Stop backfill service."""
        log.info("Stopping backfill service")
        
        if self.client:
            try:
                await self.client.close()
            except Exception as e:
                log.warning("Error closing client: %s", e)
        
        if self.mongo_client:
            try:
                self.mongo_client.close()
            except Exception as e:
                log.warning("Error closing MongoDB: %s", e)


async def backfill_single_room(room_id: str):
    """Backfill a single room."""
    config = IndexerConfig.from_env()
    backfill = MatrixBackfill(config)
    
    try:
        await backfill.connect()
        count = await backfill.backfill_room(room_id)
        log.info("Successfully backfilled %d events", count)
    except Exception as e:
        log.error("Backfill failed: %s", e, exc_info=True)
    finally:
        await backfill.stop()


async def backfill_all():
    """Backfill all rooms."""
    config = IndexerConfig.from_env()
    backfill = MatrixBackfill(config)
    
    try:
        await backfill.connect()
        results = await backfill.backfill_all_rooms()
        log.info("Backfill summary: %s", results)
    except Exception as e:
        log.error("Backfill failed: %s", e, exc_info=True)
    finally:
        await backfill.stop()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        room_id = sys.argv[1]
        log.info("Backfilling single room: %s", room_id)
        asyncio.run(backfill_single_room(room_id))
    else:
        log.info("Backfilling all rooms")
        asyncio.run(backfill_all())
