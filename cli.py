#!/usr/bin/env python3
"""
Matrix Indexer CLI - Search interface for indexed events.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, List

import click
import pymongo
from pymongo import MongoClient

from config import IndexerConfig


class MatrixIndexerCLI:
    """CLI interface for Matrix event search."""
    
    def __init__(self, config: IndexerConfig):
        self.config = config
        self.client: Optional[MongoClient] = None
        self.db = None
        self.events_collection = None
    
    def connect(self) -> None:
        """Connect to MongoDB."""
        self.client = MongoClient(self.config.mongo.uri)
        self.db = self.client[self.config.mongo.db]
        self.events_collection = self.db[self.config.mongo.events_collection]
    
    def disconnect(self) -> None:
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
    
    def search_by_room(self, room_id: str, limit: int = 50) -> List[dict]:
        """Search events by room ID."""
        cursor = self.events_collection.find(
            {"room_id": room_id},
            sort=[("origin_server_ts", pymongo.DESCENDING)],
            limit=limit
        )
        return list(cursor)
    
    def search_by_user(self, user_id: str, limit: int = 50) -> List[dict]:
        """Search events by sender user ID."""
        cursor = self.events_collection.find(
            {"sender": user_id},
            sort=[("origin_server_ts", pymongo.DESCENDING)],
            limit=limit
        )
        return list(cursor)
    
    def search_by_content(self, text: str, limit: int = 50) -> List[dict]:
        """Search events by text content."""
        cursor = self.events_collection.find(
            {"$text": {"$search": text}},
            {"score": {"$meta": "textScore"}},
            sort=[("score", {"$meta": "textScore"})],
            limit=limit
        )
        return list(cursor)
    
    def search_by_date(self, start_date: datetime, end_date: datetime, limit: int = 50) -> List[dict]:
        """Search events by date range."""
        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)
        
        cursor = self.events_collection.find(
            {
                "origin_server_ts": {
                    "$gte": start_ts,
                    "$lte": end_ts
                }
            },
            sort=[("origin_server_ts", pymongo.DESCENDING)],
            limit=limit
        )
        return list(cursor)
    
    def search_by_type(self, event_type: str, limit: int = 50) -> List[dict]:
        """Search events by type."""
        cursor = self.events_collection.find(
            {"type": event_type},
            sort=[("origin_server_ts", pymongo.DESCENDING)],
            limit=limit
        )
        return list(cursor)
    
    def get_stats(self) -> dict:
        """Get database statistics."""
        total_events = self.events_collection.count_documents({})
        message_events = self.events_collection.count_documents({"type": "m.room.message"})
        
        # Get unique rooms and users
        rooms = self.events_collection.distinct("room_id")
        users = self.events_collection.distinct("sender")
        
        return {
            "total_events": total_events,
            "message_events": message_events,
            "unique_rooms": len(rooms),
            "unique_users": len(users),
        }
    
    def format_event(self, event: dict) -> str:
        """Format event for display."""
        event_id = event.get("event_id", "unknown")
        sender = event.get("sender", "unknown")
        event_type = event.get("type", "unknown")
        ts = event.get("origin_server_ts", 0)
        
        # Format timestamp
        try:
            dt = datetime.fromtimestamp(ts / 1000)
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            ts_str = str(ts)
        
        # Get content
        content = event.get("content", {})
        body = content.get("body", "")
        
        # Format
        if body:
            return f"[{ts_str}] {sender}: {body[:80]}"
        else:
            return f"[{ts_str}] {event_type} from {sender}"


def print_events(events: List[dict], cli: MatrixIndexerCLI) -> None:
    """Print formatted events."""
    if not events:
        click.echo("No events found.")
        return
    
    click.echo(f"Found {len(events)} events:\n")
    for event in events:
        click.echo(cli.format_event(event))
    click.echo()


@click.group()
def cli():
    """Matrix Indexer CLI - Search indexed events."""
    pass


@cli.command()
def stats():
    """Show database statistics."""
    config = IndexerConfig.from_env()
    cli_obj = MatrixIndexerCLI(config)
    
    try:
        cli_obj.connect()
        stats_data = cli_obj.get_stats()
        
        click.echo("=== Matrix Indexer Statistics ===")
        click.echo(f"Total events: {stats_data['total_events']}")
        click.echo(f"Message events: {stats_data['message_events']}")
        click.echo(f"Unique rooms: {stats_data['unique_rooms']}")
        click.echo(f"Unique users: {stats_data['unique_users']}")
    
    finally:
        cli_obj.disconnect()


@cli.command()
@click.option('--room', required=True, help='Room ID to search')
@click.option('--limit', default=50, help='Maximum results')
def room(room, limit):
    """Search events by room."""
    config = IndexerConfig.from_env()
    cli_obj = MatrixIndexerCLI(config)
    
    try:
        cli_obj.connect()
        events = cli_obj.search_by_room(room, limit=limit)
        print_events(events, cli_obj)
    
    finally:
        cli_obj.disconnect()


@cli.command()
@click.option('--user', required=True, help='User ID to search')
@click.option('--limit', default=50, help='Maximum results')
def user(user, limit):
    """Search events by user."""
    config = IndexerConfig.from_env()
    cli_obj = MatrixIndexerCLI(config)
    
    try:
        cli_obj.connect()
        events = cli_obj.search_by_user(user, limit=limit)
        print_events(events, cli_obj)
    
    finally:
        cli_obj.disconnect()


@cli.command()
@click.option('--text', required=True, help='Text to search')
@click.option('--limit', default=50, help='Maximum results')
def search(text, limit):
    """Search events by content."""
    config = IndexerConfig.from_env()
    cli_obj = MatrixIndexerCLI(config)
    
    try:
        cli_obj.connect()
        events = cli_obj.search_by_content(text, limit=limit)
        print_events(events, cli_obj)
    
    finally:
        cli_obj.disconnect()


@cli.command()
@click.option('--start', required=True, help='Start date (YYYY-MM-DD)')
@click.option('--end', required=True, help='End date (YYYY-MM-DD)')
@click.option('--limit', default=50, help='Maximum results')
def date(start, end, limit):
    """Search events by date range."""
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
    except ValueError as e:
        click.echo(f"Error parsing date: {e}")
        return
    
    config = IndexerConfig.from_env()
    cli_obj = MatrixIndexerCLI(config)
    
    try:
        cli_obj.connect()
        events = cli_obj.search_by_date(start_date, end_date, limit=limit)
        print_events(events, cli_obj)
    
    finally:
        cli_obj.disconnect()


@cli.command()
@click.option('--type', required=True, help='Event type')
@click.option('--limit', default=50, help='Maximum results')
def event_type(type, limit):
    """Search events by type."""
    config = IndexerConfig.from_env()
    cli_obj = MatrixIndexerCLI(config)
    
    try:
        cli_obj.connect()
        events = cli_obj.search_by_type(type, limit=limit)
        print_events(events, cli_obj)
    
    finally:
        cli_obj.disconnect()


if __name__ == "__main__":
    cli()
