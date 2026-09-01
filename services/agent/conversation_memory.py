"""
Persistent Conversation Memory for Travel Weather Agent

Stores and retrieves conversation history in a SQLite database.

Database Schema:
---------------
conversations:
  - id: Primary key
  - user_id: User identifier (default: 'default')
  - session_id: Conversation session ID
  - role: Message role ('user', 'assistant', 'system', 'tool')
  - content: Message content (text)
  - tool_calls: JSON array of OpenAI tool call objects (when assistant uses tools)
  - metadata: JSON object with additional context
  - timestamp: Message timestamp

sessions:
  - session_id: Primary key
  - user_id: User identifier
  - title: Session title
  - created_at: Creation timestamp
  - last_activity: Last message timestamp
  - message_count: Total messages in session

Metadata Format:
---------------
User messages:
  {
    "timestamp": "ISO 8601 datetime",
    "query_length": int
  }

Assistant messages:
  {
    "timestamp": "ISO 8601 datetime",
    "model": "model name (e.g., gpt-4o-mini)",
    "had_tool_calls": bool,
    "response_length": int,
    "tool_results": [{"tool": str, "arguments": dict, "result": str}] or null
  }
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class ConversationMemory:
    """Persistent conversation memory backed by SQLite."""
    
    def __init__(self, db_path: str = "data/conversations.db"):
        """
        Initialise conversation memory backed by a database.
        
        Args:
            db_path: Sti til SQLite database fil
        """
        self.db_path = db_path
        
        # Create the data directory if it does not exist
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialise the database
        self._init_database()
        
    def _init_database(self):
        """Create the database tables if they do not already exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Main conversation table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    metadata TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Session metadata
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    title TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0
                )
            """)
            
            # Indexes, for lookup performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user_session 
                ON conversations(user_id, session_id, timestamp)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_timestamp 
                ON conversations(timestamp)
            """)
            
            conn.commit()
            logger.info(f"Database initialisert: {self.db_path}")
    
    def create_session(self, user_id: str = "default", title: Optional[str] = None) -> str:
        """
        Create a new conversation session.
        
        Args:
            user_id: the user identifier
            title: optional session title
            
        Returns:
            Session ID
        """
        session_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sessions (session_id, user_id, title)
                VALUES (?, ?, ?)
            """, (session_id, user_id, title))
            conn.commit()
            
        logger.info(f"New session created: {session_id}")
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str, 
                   tool_calls: Optional[List[Dict]] = None,
                   metadata: Optional[Dict] = None,
                   user_id: str = "default"):
        """
        Append a message to the conversation history.
        
        Args:
            session_id: the session identifier
            role: Rolle (user, assistant, system, tool)
            content: Meldingsinnhold
            tool_calls: any tool calls made
            metadata: Ekstra metadata
            user_id: the user identifier
        """
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        metadata_json = json.dumps(metadata) if metadata else None
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Append the message
            cursor.execute("""
                INSERT INTO conversations (user_id, session_id, role, content, tool_calls, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, session_id, role, content, tool_calls_json, metadata_json))
            
            # Update session statistics
            cursor.execute("""
                UPDATE sessions 
                SET last_activity = CURRENT_TIMESTAMP,
                    message_count = message_count + 1
                WHERE session_id = ?
            """, (session_id,))
            
            conn.commit()
    
    def get_conversation_history(self, session_id: str, 
                               limit: int = 50,
                               user_id: str = "default") -> List[Dict[str, Any]]:
        """
        Fetch the conversation history for a session.
        
        Args:
            session_id: the session identifier
            limit: maximum number of messages
            user_id: the user identifier
            
        Returns:
            A list of messages
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, content, tool_calls, metadata, timestamp
                FROM conversations
                WHERE user_id = ? AND session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (user_id, session_id, limit))
            
            messages = []
            for row in cursor.fetchall():
                role, content, tool_calls_json, metadata_json, timestamp = row
                
                message = {
                    "role": role,
                    "content": content,
                    "timestamp": timestamp
                }
                
                if tool_calls_json:
                    message["tool_calls"] = json.loads(tool_calls_json)
                
                if metadata_json:
                    message["metadata"] = json.loads(metadata_json)
                
                messages.append(message)
            
            return messages
    
    def get_recent_context(self, session_id: str, 
                          context_window: int = 10,
                          user_id: str = "default") -> List[Dict[str, Any]]:
        """
        Fetch recent messages for context.
        
        Args:
            session_id: the session identifier
            context_window: how many recent messages to include
            user_id: the user identifier
            
        Returns:
            Recent messages, in the OpenAI message format
        """
        messages = self.get_conversation_history(session_id, context_window, user_id)
        
        # Convert to the OpenAI message format
        openai_messages = []
        for msg in messages:
            openai_msg = {
                "role": msg["role"],
                "content": msg["content"]
            }
            
            # Include tool_calls when present
            if "tool_calls" in msg and msg["tool_calls"]:
                openai_msg["tool_calls"] = msg["tool_calls"]
            
            openai_messages.append(openai_msg)
        
        return openai_messages
    
    def get_sessions(self, user_id: str = "default", 
                    limit: int = 20) -> List[Dict[str, Any]]:
        """
        List the sessions for a user.
        
        Args:
            user_id: the user identifier
            limit: maximum number of sessions
            
        Returns:
            A list of session records
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id, title, created_at, last_activity, message_count
                FROM sessions
                WHERE user_id = ?
                ORDER BY last_activity DESC
                LIMIT ?
            """, (user_id, limit))
            
            sessions = []
            for row in cursor.fetchall():
                session_id, title, created_at, last_activity, message_count = row
                sessions.append({
                    "session_id": session_id,
                    "title": title or "Uten tittel",
                    "created_at": created_at,
                    "last_activity": last_activity,
                    "message_count": message_count
                })
            
            return sessions
    
    def delete_old_conversations(self, days_old: int = 30, 
                               user_id: Optional[str] = None):
        """
        Delete old conversations to reclaim space.
        
        Args:
            days_old: delete conversations older than this many days
            user_id: a specific user id, or None for all users
        """
        cutoff_date = datetime.now() - timedelta(days=days_old)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if user_id:
                cursor.execute("""
                    DELETE FROM conversations 
                    WHERE user_id = ? AND timestamp < ?
                """, (user_id, cutoff_date))
                
                cursor.execute("""
                    DELETE FROM sessions 
                    WHERE user_id = ? AND last_activity < ?
                """, (user_id, cutoff_date))
            else:
                cursor.execute("""
                    DELETE FROM conversations 
                    WHERE timestamp < ?
                """, (cutoff_date,))
                
                cursor.execute("""
                    DELETE FROM sessions 
                    WHERE last_activity < ?
                """, (cutoff_date,))
            
            deleted_conversations = cursor.rowcount
            conn.commit()
            
            logger.info(f"Deleted {deleted_conversations} conversations older than {days_old} days")
    
    def get_database_stats(self) -> Dict[str, Any]:
        """
        Fetch statistics about the database.
        
        Returns:
            A dictionary of database statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Conversation count
            cursor.execute("SELECT COUNT(*) FROM conversations")
            total_messages = cursor.fetchone()[0]
            
            # Session count
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]
            
            # Distinct users
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM sessions")
            unique_users = cursor.fetchone()[0]
            
            # Database size on disk
            db_size = Path(self.db_path).stat().st_size / (1024 * 1024)  # MB
            
            return {
                "total_messages": total_messages,
                "total_sessions": total_sessions,
                "unique_users": unique_users,
                "database_size_mb": round(db_size, 2),
                "database_path": self.db_path
            }
