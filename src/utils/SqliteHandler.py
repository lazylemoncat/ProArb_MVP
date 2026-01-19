"""
SQLite Handler for ProArb data persistence.

Primary SQLite storage for all data operations.
Supports both dataclasses and Pydantic BaseModel.
"""
import csv
import json
import logging
import os
import sqlite3
import tempfile
import threading
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Optional, Type, Union

import pandas as pd

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
    def _deserialize_value(value: Any, field_name: str = "") -> Any:
        """
        Deserialize value from SQLite storage back to Python type.

        Args:
            value: Value from SQLite
            field_name: Field name (for type hints)

        Returns:
            Deserialized Python value
        """
        if value is None:
            return None

        # Try to parse JSON strings (for lists, tuples, dicts)
        if isinstance(value, str):
            # Check if it looks like JSON
            stripped = value.strip()
            if stripped.startswith(('[', '{')) and stripped.endswith((']', '}')):
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass

        return value

    @staticmethod
    def query_to_dataframe(
        class_obj: Type,
        where: Optional[str] = None,
        params: tuple = (),
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        db_path: str = DEFAULT_DB_PATH
    ) -> pd.DataFrame:
        """
        Query a table and return results as pandas DataFrame.

        Args:
            class_obj: Dataclass or Pydantic model type
            where: WHERE clause (without 'WHERE' keyword)
            params: Query parameters for WHERE clause
            order_by: ORDER BY clause (without 'ORDER BY' keyword)
            limit: Maximum number of rows to return
            offset: Number of rows to skip
            db_path: Path to SQLite database

        Returns:
            pandas DataFrame with query results
        """
        rows = SqliteHandler.query_table(
            class_obj=class_obj,
            where=where,
            params=params,
            order_by=order_by,
            limit=limit,
            offset=offset,
            db_path=db_path
        )

        if not rows:
            # Return empty DataFrame with expected columns
            model_fields = SqliteHandler._get_fields(class_obj)
            columns = ['id', 'created_at'] + [name for name, _ in model_fields]
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows)

        # Deserialize JSON fields
        for col in df.columns:
            df[col] = df[col].apply(lambda x: SqliteHandler._deserialize_value(x, col))

        return df

    @staticmethod
    def export_to_csv(
        class_obj: Type,
        output_path: Optional[str] = None,
        where: Optional[str] = None,
        params: tuple = (),
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        db_path: str = DEFAULT_DB_PATH,
        include_header: bool = True
    ) -> str:
        """
        Export table data to CSV file.

        Args:
            class_obj: Dataclass or Pydantic model type
            output_path: Path for output CSV file (None = temp file)
            where: WHERE clause for filtering
            params: Query parameters
            order_by: ORDER BY clause
            limit: Maximum rows to export
            db_path: Path to SQLite database
            include_header: Whether to include header row

        Returns:
            Path to the generated CSV file
        """
        # Get data as DataFrame
        df = SqliteHandler.query_to_dataframe(
            class_obj=class_obj,
            where=where,
            params=params,
            order_by=order_by,
            limit=limit,
            db_path=db_path
        )

        # Determine output path
        if output_path is None:
            # Create temp file
            table_name = SqliteHandler._get_table_name(class_obj)
            fd, output_path = tempfile.mkstemp(suffix='.csv', prefix=f'{table_name}_')
            os.close(fd)

        # Export to CSV
        df.to_csv(output_path, index=False, header=include_header, quoting=csv.QUOTE_NONNUMERIC)

        return output_path

    @staticmethod
    def export_raw_data_by_date(
        target_date: Union[date, str],
        output_path: Optional[str] = None,
        db_path: str = DEFAULT_DB_PATH
    ) -> Optional[str]:
        """
        Export raw data for a specific date to CSV file.

        Args:
            target_date: Target date (date object or 'YYYYMMDD' string)
            output_path: Path for output CSV file (None = temp file)
            db_path: Path to SQLite database

        Returns:
            Path to the generated CSV file, or None if no data
        """
        from .save_data.save_raw_data import RawData

        # Convert date to string if needed
        if isinstance(target_date, date):
            date_str = target_date.strftime("%Y%m%d")
        else:
            date_str = target_date

        # Calculate timestamp range for the date
        try:
            target_dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            start_ts = target_dt.timestamp()
            end_ts = (target_dt.replace(hour=23, minute=59, second=59)).timestamp()
        except ValueError:
            logger.error(f"Invalid date format: {date_str}")
            return None

        # Query data for the date
        where = "utc >= ? AND utc <= ?"
        params = (start_ts, end_ts)

        df = SqliteHandler.query_to_dataframe(
            class_obj=RawData,
            where=where,
            params=params,
            order_by="utc ASC",
            db_path=db_path
        )

        if df.empty:
            logger.info(f"No raw data found for date: {date_str}")
            return None

        # Determine output path
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix='.csv', prefix=f'{date_str}_raw_')
            os.close(fd)

        # Export to CSV (exclude internal columns)
        export_cols = [col for col in df.columns if col not in ('id', 'created_at')]
        df[export_cols].to_csv(output_path, index=False, quoting=csv.QUOTE_NONNUMERIC)

        logger.info(f"Exported {len(df)} rows of raw data for {date_str} to {output_path}")
        return output_path

    @staticmethod
    def table_exists(
        class_obj: Type,
        db_path: str = DEFAULT_DB_PATH
    ) -> bool:
        """
        Check if a table exists in the database.

        Args:
            class_obj: Dataclass or Pydantic model type
            db_path: Path to SQLite database

        Returns:
            True if table exists, False otherwise
        """
        table_name = SqliteHandler._get_table_name(class_obj)
        conn = SqliteHandler._get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cursor.fetchone() is not None

    @staticmethod
    def get_distinct_values(
        class_obj: Type,
        column: str,
        where: Optional[str] = None,
        params: tuple = (),
        db_path: str = DEFAULT_DB_PATH
    ) -> list[Any]:
        """
        Get distinct values from a column.

        Args:
            class_obj: Dataclass or Pydantic model type
            column: Column name
            where: WHERE clause
            params: Query parameters
            db_path: Path to SQLite database

        Returns:
            List of distinct values
        """
        table_name = SqliteHandler._get_table_name(class_obj)

        sql = f'SELECT DISTINCT "{column}" FROM "{table_name}"'
        if where:
            sql += f" WHERE {where}"

        rows = SqliteHandler.query(sql, params, db_path)
        return [row[column] for row in rows if row[column] is not None]

    @staticmethod
    def get_latest_by_group(
        class_obj: Type,
        group_column: str,
        order_column: str = "utc",
        where: Optional[str] = None,
        params: tuple = (),
        db_path: str = DEFAULT_DB_PATH
    ) -> list[dict]:
        """
        Get the latest row for each group (e.g., latest data per market_id).

        Args:
            class_obj: Dataclass or Pydantic model type
            group_column: Column to group by (e.g., 'market_id')
            order_column: Column to determine latest (e.g., 'utc')
            where: WHERE clause for filtering
            params: Query parameters
            db_path: Path to SQLite database

        Returns:
            List of dictionaries, one per group
        """
        table_name = SqliteHandler._get_table_name(class_obj)

        # Use window function to get latest per group
        sql = f'''
            SELECT * FROM (
                SELECT *,
                    ROW_NUMBER() OVER (PARTITION BY "{group_column}" ORDER BY "{order_column}" DESC) as rn
                FROM "{table_name}"
                {f"WHERE {where}" if where else ""}
            ) WHERE rn = 1
        '''

        return SqliteHandler.query(sql, params, db_path)

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
