# Matrix Indexer

A real-time Matrix event indexer that caches incoming events and stores them in MongoDB for efficient searching and retrieval.

## Features

- **Real-time Event Caching**: LRU in-memory cache for recent events using matrix-nio AsyncClient
- **MongoDB Storage**: Persistent storage of all indexed events with full-text search
- **Historical Backfill**: Background service to recover missing historical events
- **CLI Search Interface**: Command-line tool for searching by room, user, content, date, or type
- **Async-First Design**: Built on asyncio for high performance
- **Production-Ready**: Comprehensive logging, error handling, and configuration management

## Installation

### Requirements

- Python 3.8+
- MongoDB 4.0+
- Matrix homeserver access

### Setup

1. Clone the repository:
```bash
git clone https://github.com/cyberscoob/matrix-indexer.git
cd matrix-indexer
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

### Environment Variables

```bash
# Matrix server config
export MATRIX_HOMESERVER=https://your_homeserver_url
export MATRIX_USER_ID=@your_username:your_homeserver
export MATRIX_PASSWORD=your_password_here
# OR use access token:
# export MATRIX_TOKEN=your_access_token

# MongoDB config
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB=matrix_index

# Logging
export LOG_LEVEL=INFO
```

### Config File

Alternatively, create a `config.json`:
```json
{
  "matrix": {
    "homeserver": "https://your_homeserver_url",
    "user_id": "@your_username:your_homeserver",
    "password": "your_password_here"
  },
  "mongo": {
    "uri": "mongodb://localhost:27017",
    "db": "matrix_index"
  }
}
```

## Usage

### Start the Indexer

Run the main indexer service (real-time event listening):
```bash
python indexer.py
```

### Backfill Historical Events

Backfill all joined rooms:
```bash
python backfill.py
```

Backfill a specific room:
```bash
python backfill.py "!room_id:server"
```

### Search Events

#### Show Statistics
```bash
python cli.py stats
```

#### Search by Room
```bash
python cli.py room --room "!room_id:server" --limit 50
```

#### Search by User
```bash
python cli.py user --user "@username:server" --limit 50
```

#### Search by Content
```bash
python cli.py search --text "keyword" --limit 50
```

#### Search by Date Range
```bash
python cli.py date --start 2024-01-01 --end 2024-01-31 --limit 50
```

#### Search by Event Type
```bash
python cli.py event_type --type "m.room.message" --limit 50
```

## Project Structure

- **indexer.py**: Main async indexer with real-time event listening and caching
- **backfill.py**: Historical event recovery service
- **cli.py**: Command-line search interface
- **config.py**: Configuration management with Pydantic models
- **requirements.txt**: Python dependencies
- **README.md**: This file

## Architecture

### Event Flow

1. **Real-time Listening** (`indexer.py`)
   - Connects to Matrix homeserver as authenticated user
   - Maintains persistent sync connection
   - Receives new events in real-time
   - Caches events in memory (LRU cache)
   - Stores events in MongoDB

2. **Historical Backfill** (`backfill.py`)
   - Fetches historical events from joined rooms
   - Processes events in batches to avoid rate limiting
   - Inserts missing events into database
   - Can run on-demand or as scheduled service

3. **Search Interface** (`cli.py`)
   - Connects to MongoDB
   - Provides multiple search methods
   - Formats results for display

### Data Storage

Events are stored in MongoDB with the following structure:
```json
{
  "event_id": "$event_id",
  "room_id": "!room_id:server",
  "sender": "@user:server",
  "type": "m.room.message",
  "origin_server_ts": 1704067200000,
  "timestamp": 1704067200,
  "content": {
    "body": "Message text",
    "msgtype": "m.text"
  },
  "source": {}
}
```

Indexes are created on:
- `event_id` (unique)
- `room_id`
- `sender`
- `origin_server_ts` (descending)
- `type`
- `content.body` (text search)

## Systemd Integration

### Install as Service

Copy service files to systemd directory:
```bash
sudo cp matrix-indexer.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### Start/Stop Service

```bash
# Start the service
sudo systemctl start matrix-indexer

# Enable auto-start on boot
sudo systemctl enable matrix-indexer

# Check status
sudo systemctl status matrix-indexer

# View logs
sudo journalctl -u matrix-indexer -f
```

## Performance Tuning

- **Cache Size**: Adjust `cache_size` in config for more/less memory usage
- **Sync Timeout**: Increase `sync_timeout_ms` for lower latency with higher CPU/network usage
- **Backfill Batch Size**: Adjust `backfill_batch_size` to balance memory and rate limiting
- **MongoDB**: Create appropriate indexes and tune connection pooling

## Error Handling

The indexer includes:
- Automatic reconnection with exponential backoff
- Event deduplication
- Invalid event filtering
- Comprehensive logging
- Graceful shutdown on signals

## Development

### Adding Custom Event Handlers

Extend `MatrixIndexer` class to add custom event processing:

```python
async def _process_events(self, events):
    for event in events:
        if event.type == "m.room.message":
            # Custom handling
            await self.handle_message(event)
```

### Running Tests

```bash
# TODO: Add test suite
```

## Troubleshooting

### MongoDB Connection Errors
- Ensure MongoDB is running: `mongo --version`
- Check connection string in configuration
- Verify network connectivity to MongoDB server

### Matrix Authentication Failures
- Verify credentials (user_id, password)
- Check homeserver URL
- Ensure user has access to desired rooms

### Low Indexing Performance
- Check network latency to Matrix server
- Increase `sync_timeout_ms` to batch more events
- Monitor MongoDB write performance
- Reduce `cache_size` if memory-constrained

## License

MIT

## Contributing

Contributions welcome! Please submit pull requests to https://github.com/cyberscoob/matrix-indexer
