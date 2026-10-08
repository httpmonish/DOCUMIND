# 0007. Local Storage Layout and Source Naming

## Context
DocuMind indexes local documents and generates persistent vector indexes, metadata state, and log files. The storage layout must be deterministic across environments and prevent path collisions or directory traversal.

## Options with numbers
1. **Repository-Local `./data` directory**:
   - Commits or mixes runtime data into the git working tree.
   - Breaks if the CLI or scripts are executed from different working directories.
2. **Platform-specific directories via `platformdirs`**:
   - Adds an external dependency.
   - Places files across scattered OS-specific locations (`~/Library/Application Support`, `%APPDATA%`, `~/.local/share`).
3. **Dedicated Home Directory (`DOCUMIND_HOME`, default `~/.documind`)** (Chosen):
   - Zero extra dependencies.
   - Clean, predictable layout:
     ```
     ~/.documind/
       chroma/       Embedded vector storage (644 KB on fixtures)
       meta.json     {"schema_version": 1, "embed_model": "..."}
       uploads/      REST upload staging
       logs/         Execution & query logs
     ```
   - Collection naming: `documind__{model_slug}__s{schema_version}` binds embeddings to the model version.
   - Sources are strictly relative POSIX paths (never absolute, no `..` traversal).

## Decision
Adopt `~/.documind` (configurable via `DOCUMIND_HOME`) as the global storage root. Require all source keys to be normalized relative to indexing root using `normalize_source()`.

## You give up X to get Y
You give up OS-native application directory conventions to get **zero runtime dependencies, predictable location across platforms, and isolation from the git tree**.

## Revisit when
DocuMind is packaged as an OS-level desktop installer.
