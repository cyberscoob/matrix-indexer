#!/usr/bin/env python3
"""
Matrix Event Indexer - Real-time event caching and storage.
"""
import asyncio
import logging
import json
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Dict, Any, List

import pymongo
from nio import (
    AsyncClient, SyncResponse, RoomMessageText, RoomMemberEvent,
    RoomNameEvent, RoomTopicEvent, RoomAvatarEvent, RoomCreateEvent
)

from config import IndexerConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("matrix_indexer")


class EventCache:
    """In-memory LRU cache for recent events."""
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
    
    def add(self, event_id: str, event: Dict[str, Any]) -> None:
        """Add event to cache, removing oldest if at capacity."""
        self.cache[event_id] = event
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)
    
    def get(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get event from cache."""
        return self.cache.get(event_id)
    
    def contains(self, event_id: str) -> bool:
        """Check if event is in cache."""
        return event_id in self.cache
    
    def size(self) -> int:
        """Get cache size."""
        return len(self.cache)


class MatrixIndexer:
    """Main Matrix event indexer."""
    
    def __init__(self, config: IndexerConfig):
        self.config = config
        self.client: Optional[AsyncClient] = None
        self.mongo_client: Optional[pymongo.MongoClient] = None
        self.db = None
        self.events_collection = None
        self.rooms_collection = None
        self.users_collection = None
        self.cache = EventCache(max_size=config.cache_size)
        self.running = False
        self.sync_token: Optional[str] = None
        
        log.setLevel(getattr(logging, config.log_level))
    
    async def connect(self) -> None:
        """Initialize connections to Matrix and MongoDB."""
        log.info("Initializing Matrix client for %s", self.config.matrix.user_id)
        
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
            resp = await self.client.login(self.config.matrix.password, device_name=self.config.matrix.device_name)
            if hasattr(resp, 'access_token'):
                self.config.matrix.access_token = resp.access_token
                log.info("Successfully logged in, got access token")
            else:
                raise RuntimeError(f"Login failed: {resp}")
        else:
            raise ValueError("Either password or access_token must be provided")
        
        # Connect to MongoDB
        log.info("Connecting to MongoDB at %s", self.config.mongo.uri)
        self.mongo_client = pymongo.MongoClient(self.config.mongo.uri)
        self.db = self.mongo_client[self.config.mongo.db]
        self.events_collection = self.db[self.config.mongo.events_collection]
        self.rooms_collection = self.db[self.config.mongo.rooms_collection]
        self.users_collection = self.db[self.config.mongo.users_collection]
        
        # Create indexes
        self._create_indexes()
        
        # Load sync token from state file
        self._load_state()
        
        log.info("Successfully initialized connections")
    
    def _create_indexes(self) -> None:
        """Create MongoDB indexes for efficient querying."""
        try:
            self.events_collection.create_index([("event_id", pymongo.ASCENDING)], unique=True)
            self.events_collection.create_index([("room_id", pymongo.ASCENDING)])
            self.events_collection.create_index([("sender", pymongo.ASCENDING)])
            self.events_collection.create_index([("origin_server_ts", pymongo.DESCENDING)])
            self.events_collection.create_index([("type", pymongo.ASCENDING)])
            
            # Text search index on content
            self.events_collection.create_index([("content.body", pymongo.TEXT)])
            
            log.info("Created MongoDB indexes")
        except Exception as e:
            log.warning("Error creating indexes: %s", e)
    
    def _load_state(self) -> None:
        """Load sync token from state file."""
        if self.config.state_file.exists():
            try:
                state = json.loads(self.config.state_file.read_text())
                self.sync_token = state.get("sync_token")
                log.info("Loaded sync_token: %s", self.sync_token)
            except Exception as e:
                log.warning("Error loading state: %s", e)
    
    def _save_state(self) -> None:
        """Save sync token to state file."""
        try:
            self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {"sync_token": self.sync_token}
            self.config.state_file.write_text(json.dumps(state))
        except Exception as e:
            log.warning("Error saving state: %s", e)
    
    def _serialize_event(self, event: Any) -> Dict[str, Any]:
        """Serialize Matrix event to JSON-friendly dict."""
        doc = {
            "event_id": getattr(event, "event_id", None),
            "room_id": getattr(event, "room_id", None),
            "sender": getattr(event, "sender", None),
            "type": getattr(event, "type", None),
            "origin_server_ts": getattr(event, "origin_server_ts", None),
            "timestamp": int(getattr(event, "timestamp", 0)),
            "source": getattr(event, "source", {}),
        }
        
        # Extract body for text events
        if isinstance(event, RoomMessageText):
            doc["content"] = {"body": event.body, "msgtype": event.msgtype}
        elif hasattr(event, 'content'):
            doc["content"] = event.content if isinstance(event.content, dict) else {}
        else:
            doc["content"] = {}
        
        return doc
    
    async def _process_events(self, events: List[Any]) -> None:
        """Process and store events."""
        if not events:
            return
        
        docs_to_insert = []
        
        for event in events:
            if not hasattr(event, 'event_id') or not event.event_id:
                continue
            
            doc = self._serialize_event(event)
            docs_to_insert.append(doc)
            
            # Add to cache
            self.cache.add(event.event_id, doc)
        
        if docs_to_insert:
            try:
                # Insert with replace_one to handle duplicates
                for doc in docs_to_insert:
                    self.events_collection.replace_one(
                        {"event_id": doc["event_id"]},
                        doc,
                        upsert=True
                    )
                log.info("Stored %d events in MongoDB", len(docs_to_insert))
            except Exception as e:
                log.error("Error storing events: %s", e)
    
    async def sync_loop(self) -> None:
        """Main sync loop for real-time event listening."""
        self.running = True
        log.info("Starting sync loop")
        
        try:
            while self.running:
                try:
                    log.debug("Syncing with token=%s", self.sync_token)
                    resp = await self.client.sync(timeout_ms=self.config.sync_timeout_ms, since=self.sync_token)
                    
                    if isinstance(resp, SyncResponse):
                        self.sync_token = resp.next_batch
                        self._save_state()
                        
                        # Process events from all joined rooms
                        for room_id, room_data in resp.rooms.join.items():
                            if room_data.timeline.events:
                                await self._process_events(room_data.timeline.events)
                        
                        log.debug("Sync complete, next_batch=%s", resp.next_batch)
                    else:
                        log.error("Sync failed: %s", resp)
                        await asyncio.sleep(5)  # Back off on error
                
                except Exception as e:
                    log.error("Error in sync loop: %s", e, exc_info=True)
                    await asyncio.sleep(5)  # Back off on error
        
        except asyncio.CancelledError:
            log.info("Sync loop cancelled")
            self.running = False
        finally:
            log.info("Sync loop stopped")
    
    async def stop(self) -> None:
        """Stop the indexer."""
        log.info("Stopping indexer")
        self.running = False
        
        if self.client:
            try:
                await self.client.close()
            except Exception as e:
                log.warning("Error closing Matrix client: %s", e)
        
        if self.mongo_client:
            try:
                self.mongo_client.close()
            except Exception as e:
                log.warning("Error closing MongoDB client: %s", e)
        
        log.info("Indexer stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get indexer statistics."""
        try:
            event_count = self.events_collection.count_documents({})
            room_count = self.rooms_collection.count_documents({})
            user_count = self.users_collection.count_documents({})
        except Exception as e:
            log.warning("Error getting stats: %s", e)
            event_count = room_count = user_count = 0
        
        return {
            "running": self.running,
            "cache_size": self.cache.size(),
            "events_in_db": event_count,
            "rooms_in_db": room_count,
            "users_in_db": user_count,
            "sync_token": self.sync_token,
        }


async def main():
    """Main entry point."""
    # Load config from environment variables and defaults
    config = IndexerConfig.from_env()
    
    log.info("Starting Matrix Indexer")
    log.info("Homeserver: %s", config.matrix.homeserver)
    log.info("User: %s", config.matrix.user_id)
    log.info("MongoDB: %s", config.mongo.uri)
    
    indexer = MatrixIndexer(config)
    
    try:
        await indexer.connect()
        log.info("Connected successfully")
        
        # Start sync loop
        await indexer.sync_loop()
    
    except KeyboardInterrupt:
        log.info("Received keyboard interrupt")
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
    finally:
        await indexer.stop()
        log.info("Exited")


if __name__ == "__main__":
    asyncio.run(main())
