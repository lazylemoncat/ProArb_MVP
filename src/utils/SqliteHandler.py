"""
SQLite Handler for ProArb data persistence.

Provides parallel SQLite storage alongside CSV for all data operations.
Supports both dataclasses and Pydantic BaseModel.
"""
import json
import logging
import sqlite3
import threading
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Type

logger = logging.getLogger(__name__)


def is_pydantic_model(cls: Type) -> bool:
    """Check if a class is a Pydantic BaseModel."""
    try:
        from pydantic import BaseModel
        return isinstance(cls, type) and issubclass(cls, BaseModel)
    except ImportError:
        return False


def get_pydantic_fields(cls: Type) -> list[tuple[str, Any]]:
    """Get field names and types from a Pydantic model."""
    if hasattr(cls, 'model_fields'):
        # Pydantic v2
        return [(name, field.annotation) for name, field in cls.model_fields.items()]
    elif hasattr(cls, '__fields__'):
        # Pydantic v1
        return [(name, field.outer_type_) for name, field in cls.__fields__.items()]
    return []

# Thread-local storage for SQLite connections
_local = threading.local()

# Default database path
DEFAULT_DB_PATH = "./data/proarb.db"


class SqliteHandler:
    """
    SQLite handler for saving dataclass objects to SQLite database.

    Usage:
        from src.utils.SqliteHandler import SqliteHandler
        from dataclasses import asdict

        # Save a dataclass object
        SqliteHandler.save_to_db(row_dict=asdict(my_dataclass), class_obj=MyDataclass)

        # Query data
        rows = SqliteHandler.query("SELECT * FROM my_dataclass WHERE id = ?", (1,))
    """

    _initialized_tables: set[str] = set()
    _lock = threading.Lock()

    @staticmethod
    def _get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
        """
        Get thread-local SQLite connection.

        Args:
            db_path: Path to SQLite database file

        Returns:
            sqlite3.Connection object
        """
        if not hasattr(_local, 'connections'):
            _local.connections = {}

        if db_path not in _local.connections:
            # Ensure directory exists
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _local.connections[db_path] = conn

        return _local.connections[db_path]

    @staticmethod
    def _python_type_to_sqlite(py_type: Any) -> str:
        """
        Convert Python type to SQLite type.

        Args:
            py_type: Python type annotation

        Returns:
            SQLite type string
        """
        # Handle Optional types
        type_str = str(py_type)
        if 'Optional' in type_str:
            # Extract inner type from Optional[X]
            if hasattr(py_type, '__args__') and py_type.__args__:
                py_type = py_type.__args__[0]

        # Map Python types to SQLite types
        type_mapping = {
            int: "INTEGER",
            float: "REAL",
            str: "TEXT",
            bool: "INTEGER",  # SQLite has no boolean, use 0/1
            datetime: "TEXT",  # Store as ISO format string
            list: "TEXT",      # Store as JSON
            tuple: "TEXT",     # Store as JSON
            dict: "TEXT",      # Store as JSON
        }

        # Get the base type
        if hasattr(py_type, '__origin__'):
            # Handle generic types like List[int]
            return "TEXT"  # Store as JSON

        return type_mapping.get(py_type, "TEXT")

    @staticmethod
    def _serialize_value(value: Any, field_type: Any) -> Any:
        """
        Serialize Python value for SQLite storage.

        Args:
            value: Value to serialize
            field_type: Field type annotation

        Returns:
            Serialized value suitable for SQLite
        """
        if value is None:
            return None

        # Handle complex types that need JSON serialization
        if isinstance(value, (list, tuple, dict)):
            return json.dumps(value)

        # Handle datetime
        if isinstance(value, datetime):
            return value.isoformat()

        # Handle boolean
        if isinstance(value, bool):
            return 1 if value else 0

        return value

    @staticmethod
    def _get_table_name(class_obj: Type) -> str:
        """
        Get table name from dataclass.

        Args:
            class_obj: Dataclass type

        Returns:
            Table name (lowercase class name)
        """
        return class_obj.__name__.lower()

    @staticmethod
    def _get_fields(class_obj: Type) -> list[tuple[str, Any]]:
        """
        Get field names and types from dataclass or Pydantic model.

        Args:
            class_obj: Dataclass or Pydantic model type

        Returns:
            List of (field_name, field_type) tuples
        """
        if is_dataclass(class_obj):
            return [(f.name, f.type) for f in fields(class_obj)]
        elif is_pydantic_model(class_obj):
            return get_pydantic_fields(class_obj)
        else:
            raise ValueError(f"{class_obj} is not a dataclass or Pydantic model")

    @staticmethod
    def _ensure_table(class_obj: Type, db_path: str = DEFAULT_DB_PATH) -> None:
        """
        Ensure table exists for the given dataclass or Pydantic model.
        Creates or alters table as needed.

        Args:
            class_obj: Dataclass or Pydantic model type
            db_path: Path to SQLite database
        """
        if not is_dataclass(class_obj) and not is_pydantic_model(class_obj):
            raise ValueError(f"{class_obj} is not a dataclass or Pydantic model")

        table_name = SqliteHandler._get_table_name(class_obj)
        cache_key = f"{db_path}:{table_name}"

        # Skip if already initialized in this session
        if cache_key in SqliteHandler._initialized_tables:
            return

        with SqliteHandler._lock:
            # Double-check after acquiring lock
            if cache_key in SqliteHandler._initialized_tables:
                return

            conn = SqliteHandler._get_connection(db_path)
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            table_exists = cursor.fetchone() is not None

            # Get fields from dataclass or Pydantic model
            model_fields = SqliteHandler._get_fields(class_obj)

            if not table_exists:
                # Create new table
                columns = []
                columns.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
                columns.append("created_at TEXT DEFAULT CURRENT_TIMESTAMP")

                for field_name, field_type in model_fields:
                    sql_type = SqliteHandler._python_type_to_sqlite(field_type)
                    columns.append(f'"{field_name}" {sql_type}')

                create_sql = f'CREATE TABLE "{table_name}" ({", ".join(columns)})'
                cursor.execute(create_sql)

                # Create indexes on common fields
                index_fields = ['timestamp', 'time', 'market_id', 'signal_id', 'trade_id', 'utc']
                for idx_field in index_fields:
                    if any(field_name == idx_field for field_name, _ in model_fields):
                        try:
                            cursor.execute(
                                f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{idx_field}" '
                                f'ON "{table_name}" ("{idx_field}")'
                            )
                        except sqlite3.OperationalError:
                            pass  # Index might already exist

                conn.commit()
                logger.info(f"Created SQLite table: {table_name}")
            else:
                # Table exists, check for missing columns
                cursor.execute(f'PRAGMA table_info("{table_name}")')
                existing_columns = {row[1] for row in cursor.fetchall()}

                for field_name, field_type in model_fields:
                    if field_name not in existing_columns:
                        sql_type = SqliteHandler._python_type_to_sqlite(field_type)
                        try:
                            cursor.execute(
                                f'ALTER TABLE "{table_name}" ADD COLUMN "{field_name}" {sql_type}'
                            )
                            logger.info(f"Added column {field_name} to table {table_name}")
                        except sqlite3.OperationalError as e:
                            logger.warning(f"Failed to add column {field_name}: {e}")

                conn.commit()

            SqliteHandler._initialized_tables.add(cache_key)

    @staticmethod
    def save_to_db(
        row_dict: dict[str, Any],
        class_obj: Type,
        db_path: str = DEFAULT_DB_PATH
    ) -> int:
        """
        Save a row to SQLite database.

        Args:
            row_dict: Dictionary of field values (from asdict() or model_dump())
            class_obj: Dataclass or Pydantic model type for schema reference
            db_path: Path to SQLite database

        Returns:
            Row ID of inserted record
        """
        if not is_dataclass(class_obj) and not is_pydantic_model(class_obj):
            raise ValueError(f"{class_obj} is not a dataclass or Pydantic model")

        # Ensure table exists
        SqliteHandler._ensure_table(class_obj, db_path)

        table_name = SqliteHandler._get_table_name(class_obj)

        # Get fields from dataclass or Pydantic model
        model_fields = SqliteHandler._get_fields(class_obj)

        # Build field type mapping
        field_types = {name: ftype for name, ftype in model_fields}

        # Prepare columns and values
        columns = []
        placeholders = []
        values = []

        for field_name, field_type in model_fields:
            if field_name in row_dict:
                columns.append(f'"{field_name}"')
                placeholders.append("?")
                value = SqliteHandler._serialize_value(row_dict[field_name], field_types[field_name])
                values.append(value)

        # Insert row
        insert_sql = f'INSERT INTO "{table_name}" ({", ".join(columns)}) VALUES ({", ".join(placeholders)})'

        conn = SqliteHandler._get_connection(db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(insert_sql, values)
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"SQLite insert error: {e}", exc_info=True)
            raise

    @staticmethod
    def query(
        sql: str,
        params: tuple = (),
        db_path: str = DEFAULT_DB_PATH
    ) -> list[dict]:
        """
        Execute a query and return results as list of dicts.

        Args:
            sql: SQL query string
            params: Query parameters
            db_path: Path to SQLite database

        Returns:
            List of dictionaries
        """
        conn = SqliteHandler._get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    @staticmethod
    def query_table(
        class_obj: Type,
        where: Optional[str] = None,
        params: tuple = (),
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        db_path: str = DEFAULT_DB_PATH
    ) -> list[dict]:
        """
        Query a table by dataclass type.

        Args:
            class_obj: Dataclass type
            where: WHERE clause (without 'WHERE' keyword)
            params: Query parameters for WHERE clause
            order_by: ORDER BY clause (without 'ORDER BY' keyword)
            limit: Maximum number of rows to return
            offset: Number of rows to skip
            db_path: Path to SQLite database

        Returns:
            List of dictionaries
        """
        table_name = SqliteHandler._get_table_name(class_obj)

        sql = f'SELECT * FROM "{table_name}"'

        if where:
            sql += f" WHERE {where}"

        if order_by:
            sql += f" ORDER BY {order_by}"

        if limit is not None:
            sql += f" LIMIT {limit}"
            if offset > 0:
                sql += f" OFFSET {offset}"

        return SqliteHandler.query(sql, params, db_path)

    @staticmethod
    def count(
        class_obj: Type,
        where: Optional[str] = None,
        params: tuple = (),
        db_path: str = DEFAULT_DB_PATH
    ) -> int:
        """
        Count rows in a table.

        Args:
            class_obj: Dataclass type
            where: WHERE clause (without 'WHERE' keyword)
            params: Query parameters
            db_path: Path to SQLite database

        Returns:
            Number of rows
        """
        table_name = SqliteHandler._get_table_name(class_obj)

        sql = f'SELECT COUNT(*) as cnt FROM "{table_name}"'

        if where:
            sql += f" WHERE {where}"

        result = SqliteHandler.query(sql, params, db_path)
        return result[0]['cnt'] if result else 0

    @staticmethod
    def update(
        class_obj: Type,
        set_values: dict[str, Any],
        where: str,
        params: tuple = (),
        db_path: str = DEFAULT_DB_PATH
    ) -> int:
        """
        Update rows in a table.

        Args:
            class_obj: Dataclass or Pydantic model type
            set_values: Dictionary of column -> new value
            where: WHERE clause (without 'WHERE' keyword)
            params: Query parameters for WHERE clause
            db_path: Path to SQLite database

        Returns:
            Number of rows updated
        """
        if not is_dataclass(class_obj) and not is_pydantic_model(class_obj):
            raise ValueError(f"{class_obj} is not a dataclass or Pydantic model")

        table_name = SqliteHandler._get_table_name(class_obj)
        model_fields = SqliteHandler._get_fields(class_obj)
        field_types = {name: ftype for name, ftype in model_fields}

        # Build SET clause
        set_parts = []
        set_params = []

        for col, val in set_values.items():
            set_parts.append(f'"{col}" = ?')
            serialized = SqliteHandler._serialize_value(val, field_types.get(col))
            set_params.append(serialized)

        sql = f'UPDATE "{table_name}" SET {", ".join(set_parts)} WHERE {where}'
        all_params = tuple(set_params) + params

        conn = SqliteHandler._get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute(sql, all_params)
        conn.commit()

        return cursor.rowcount

    @staticmethod
    def delete(
        class_obj: Type,
        where: str,
        params: tuple = (),
        db_path: str = DEFAULT_DB_PATH
    ) -> int:
        """
        Delete rows from a table.

        Args:
            class_obj: Dataclass type
            where: WHERE clause (without 'WHERE' keyword)
            params: Query parameters
            db_path: Path to SQLite database

        Returns:
            Number of rows deleted
        """
        table_name = SqliteHandler._get_table_name(class_obj)

        sql = f'DELETE FROM "{table_name}" WHERE {where}'

        conn = SqliteHandler._get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute(sql, params)
        conn.commit()

        return cursor.rowcount

    @staticmethod
    def close_all() -> None:
        """Close all thread-local connections."""
        if hasattr(_local, 'connections'):
            for conn in _local.connections.values():
                try:
                    conn.close()
                except Exception:
                    pass
            _local.connections.clear()
