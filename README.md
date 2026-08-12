<div align="center">

![Header](https://capsule-render.vercel.app/api?type=waving&color=0:4F46E5,100:0EA5E9&height=200&section=header&text=DocuMind&fontSize=70&fontColor=ffffff&fontAlignY=35&animation=fadeIn)

[![Typing SVG](https://readme-typing-svg.demolab.com/?font=Fira+Code&size=20&pause=1000&color=4F46E5&center=true&vCenter=true&width=650&lines=RAG-powered+document+Q+%26+A;Ask+questions%2C+get+grounded+answers;CLI+%2B+REST+API+%2B+Claude+Desktop+plugin)](https://git.io/typing-svg)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Status](https://img.shields.io/badge/Status-In_Progress-orange.svg)

</div>

> **Status note:** this README documents the plan. Nothing here claims to be finished until it's actually built *and* tested.

Ask questions about your own documents — PDFs, text files, markdown notes — and get answers grounded in what those documents actually say, not the AI's general knowledge and not a guess. Built using **RAG (Retrieval-Augmented Generation)**.

## What This Project Is Designed To Demonstrate

- A full **RAG pipeline** — retrieval *and* generation, backed by a real vector database, not just a single API call
- **One engine, three interfaces** — CLI, REST API, and a native **MCP** integration for Claude Desktop, all sharing identical core logic
- **Security considered from the start** — planned API-key auth, upload validation, and prompt-injection mitigation
- **Clean separation of concerns** — the retrieval engine has zero knowledge of which interface is calling it

## Table of Contents
- [The Big Picture](#the-big-picture)
- [How It Will Work](#how-it-will-work)
- [Planned Tech Stack](#planned-tech-stack)
- [Why I'm Building This](#why-im-building-this)
- [Setup](#setup)

## The Big Picture

One engine, three ways to use it.

```mermaid
flowchart TB
    U([You]) --> CLI[CLI]
    U --> API[REST API]
    U --> MCP[MCP Server]
    CLI --> RP["core/rag_pipeline.py"]
    API --> RP
    MCP --> RP
    RP --> VDB[(ChromaDB)]
    RP --> Claude[Claude API]
```

All three interfaces call the exact same underlying engine — nothing duplicated between them.

## How It Will Work

**Adding a document (indexing):**

```mermaid
flowchart LR
    A[Document] --> B[loader.py]
    B -->|raw text| C[chunker.py]
    C -->|chunks| D[embedder.py]
    D -->|vectors| E[(ChromaDB)]
```

**Asking a question (query):**

```mermaid
flowchart LR
    Q[Your question] --> M[embedder.py]
    M -->|vector| S[ChromaDB]
    S -->|closest chunks| P[build prompt]
    P --> C[Claude API]
    C -->|answer + sources| R[Response]
```

**Asking through Claude Desktop (MCP):**

```mermaid
sequenceDiagram
    participant You
    participant Desktop as Claude Desktop
    participant Server as MCP Server
    participant Engine as rag_pipeline.py

    You->>Desktop: Search my documents for X
    Desktop->>Server: search_documents(question)
    Server->>Engine: answer_question(question)
    Engine-->>Server: answer + sources
    Server-->>Desktop: formatted result
    Desktop-->>You: shows the answer
```

## Planned Tech Stack

| Piece | Tool | Why |
|---|---|---|
| PDF reading | pypdf | pulls text out of PDF files |
| Embeddings | sentence-transformers | free, runs locally, no API cost |
| Vector storage | ChromaDB | stores + searches embeddings, no server setup needed |
| Answer generation | Claude API | writes the final answer, grounded in retrieved text |
| REST API | FastAPI | exposes this over HTTP, with free auto-generated docs |
| Desktop integration | MCP | lets Claude Desktop call this project directly as a tool |

