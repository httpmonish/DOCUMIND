# SQLite Architecture and Storage Engine

SQLite is a C-language library that implements a small, fast, self-contained, high-reliability, full-featured SQL database engine. SQLite is the most used database engine in the world. SQLite is an embedded SQL database engine. Unlike most other SQL databases, SQLite does not have a separate server process. SQLite reads and writes directly to ordinary disk files.

## The B-Tree Subsystem

SQLite stores database tables and indices using a B-Tree structure. A B-Tree organizes data into fixed-size pages, typically 4096 bytes each. Table B-Trees store 64-bit integer keys called ROWIDs and binary payloads containing column values. Index B-Trees store arbitrary keys and provide rapid lookup capabilities. The pager layer below the B-Tree handles caching pages in memory and writing them safely to disk.

## Atomic Commit and Rollback Journal

SQLite guarantees atomic transactions using a rollback journal or write-ahead log. In rollback journal mode, before modifying any database page on disk, SQLite writes the original, unmodified page content into a separate journal file. If a crash or power failure occurs during a write transaction, SQLite reads the journal file upon reopening and restores all original pages, rolling back the incomplete transaction.

## Write-Ahead Logging (WAL) Mode

Beginning with SQLite version 3.7.0, write-ahead logging (WAL) became available as an alternative concurrency mode. In WAL mode, changes are appended to a separate WAL file rather than overwriting the main database file in place. This provides two major advantages: readers do not block writers, and a writer does not block readers. Readers see a consistent snapshot of the database while writes are actively appending to the WAL. Periodically, changes in the WAL file are copied back into the main database file during a checkpoint operation.
