# 0007. Local Storage Layout and Upload Isolation

## Context
DocuMind indexes local documents and handles untrusted file uploads via its REST interface. The storage subsystem must persist vector embeddings, metadata state, query logs, and staged upload files deterministically without allowing path collisions, symlink escapes, or directory traversal.

## Options
1. **Repository-Local `./data` Directory**:
   - Commits or mixes runtime data into the git working tree.
   - Breaks if the CLI or REST server is executed from different working directories.
2. **Platform-Specific Directories via `platformdirs`**:
   - Adds an external dependency.
   - Scatters application data across disparate OS locations (`~/Library/Application Support`, `%APPDATA%`, `~/.local/share`), complicating inspection and backup for educational projects.
3. **Dedicated Home Root (`~/.documind`) with Staged Upload Prefixing (Chosen)**:
   - Root is `$DOCUMIND_HOME` (defaulting to `~/.documind`).
   - Clean, predictable directory structure:
     ```text
     ~/.documind/
       chroma/       Embedded vector storage (PersistentClient)
       meta.json     Schema and model version binding
       uploads/      Content-addressed upload staging: <sha256[:16]>_<safe_name>
       logs/         Structured query execution logs (queries.jsonl)
     ```
   - All upload filenames are sanitized using `safe_upload_name()` to strip directory navigation (`..`), leading dots, NUL bytes, and Windows reserved device names (`CON`, `NUL`, etc.).
   - Upload staging asserts `final_path.is_relative_to(uploads_dir.resolve())`.
   - Indexing writes follow strict ordering: delete old chunks, upsert chunks 1..n, upsert chunk 0 last. If any step fails, `finally: delete_source()` purges partial writes.

## Decision
Adopt Option 3. Use `$DOCUMIND_HOME` (default `~/.documind`) for all persistent state. Isolate REST uploads into `uploads/<sha256[:16]>_<safe_name>`. Normalize all source identifiers relative to the indexing root with POSIX separators. Enforce atomic replacement write ordering to ensure no orphaned chunks persist if indexing is interrupted.

## You give up X to get Y
You give up OS-native multi-directory conventions to get **deterministic zero-dependency state layout, content-addressed upload deduplication, complete traversal defense, and atomic write reliability**.

## Revisit when
DocuMind is packaged as a native OS desktop application with platform installer sandboxing requirements.
