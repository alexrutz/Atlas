"""
Database models (ORM) - Each class maps to a PostgreSQL table.

The data model:
  - User: A person who can log in and ask questions
  - Group: A group of users (e.g. "Engineering", "HR")
  - UserGroup: Links users to groups (many-to-many)
  - Collection: A set of related documents (e.g. "Technical Manuals")
  - GroupCollectionAccess: Which groups can read/write which collections
  - Document: An uploaded file (PDF, DOCX, etc.)
  - Chunk: A small piece of text from a document (used for search)
  - ChunkEmbedding: The vector representation of a chunk (for similarity search)
  - Conversation: A chat session between a user and the system
  - Message: A single message in a conversation (user question or assistant answer)
  - UserSelectedCollection: Which collections a user has selected for searching
  - SystemSetting: Key-value store for global settings (e.g. prompts, context)
"""

from app.models.user import User
from app.models.group import Group, UserGroup
from app.models.collection import Collection, GroupCollectionAccess
from app.models.document import Document
from app.models.chunk import Chunk, ChunkEmbedding
from app.models.conversation import Conversation, Message, UserSelectedCollection
from app.models.system_setting import SystemSetting

__all__ = [
    "User", "Group", "UserGroup",
    "Collection", "GroupCollectionAccess",
    "Document", "Chunk", "ChunkEmbedding",
    "Conversation", "Message", "UserSelectedCollection",
    "SystemSetting",
]
