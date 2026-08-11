<div align="center">

![Header](https://capsule-render.vercel.app/api?type=waving&color=0:4F46E5,100:0EA5E9&height=200&section=header&text=DocuMind&fontSize=70&fontColor=ffffff&fontAlignY=35&animation=fadeIn)

[![Typing SVG](https://readme-typing-svg.demolab.com/?font=Fira+Code&size=20&pause=1000&color=4F46E5&center=true&vCenter=true&width=650&lines=RAG-powered+document+Q+%26+A;Ask+questions%2C+get+grounded+answers;CLI+%2B+REST+API+%2B+Claude+Desktop+plugin)](https://git.io/typing-svg)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Status](https://img.shields.io/badge/Status-In_Progress-orange.svg)

</div>

> **Status note:** this README documents the plan. Checkboxes below get ticked off only once that piece is actually built *and* tested — not before.

Ask questions about your own documents — PDFs, text files, markdown notes — and get answers grounded in what those documents actually say, not the AI's general knowledge and not a guess. Built using **RAG (Retrieval-Augmented Generation)**.

## Table of Contents
- [The Big Picture](#the-big-picture)
- [How It Will Work](#how-it-will-work)
- [Roadmap](#roadmap)
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

    CLI --> RP
    API --> RP
    MCP --> RP

    subgraph core["core/ — the engine"]
        RP[rag_pipeline.py]
    end

    RP --> VDB[(ChromaDB<br/>vector store)]
    RP --> Claude[Claude API]
```

All three interfaces call the exact same underlying engine — nothing is duplicated between them.

## How It Will Work

**Adding a document (indexing):**

```mermaid
flowchart LR
    A["📄 Document"] --> B["loader.py<br/>extract text"]
    B --> C["chunker.py<br/>split into overlapping chunks"]
    C --> D["embedder.py<br/>text → vector"]
    D --> E[("ChromaDB")]
```

**Asking a question (query):**

```mermaid
flowchart LR
    Q["❓ Your question"] --> E1["embedder.py<br/>question → vector"]
    E1 --> S["ChromaDB<br/>find closest chunks"]
    S --> P["build prompt<br/>with retrieved context"]
    P --> C["Claude API"]
    C --> A["✅ Answer + sources"]
```

**Asking through Claude Desktop (MCP):**

```mermaid
sequenceDiagram
    participant You
    participant Desktop as Claude Desktop
    participant Server as MCP Server
    participant Engine as rag_pipeline.py

    You->>Desktop: "Search my documents for X"
    Desktop->>Server: calls search_documents(question)
    Server->>Engine: answer_question(question)
    Engine-->>Server: answer + sources
    Server-->>Desktop: formatted result
    Desktop-->>You: shows the answer in chat
```

## Roadmap

- [x] Project folder + git + GitHub connected
- [ ] Virtual environment + dependencies
- [ ] Document loader (PDF/TXT/MD → text)
- [ ] Chunking (splitting text into searchable pieces)
- [ ] Embeddings (text → numbers, for semantic search)
- [ ] Vector storage (ChromaDB)
- [ ] RAG pipeline (retrieval + Claude API answer generation)
- [ ] Command-line interface
- [ ] REST API (FastAPI)
- [ ] MCP server (Claude Desktop integration)
- [ ] Automated tests
- [ ] Security review (auth, file validation, prompt injection)
- [ ] Optional: RAG quality evaluation (RAGAS)

## Planned Tech Stack

| Piece | Tool | Why |
|---|---|---|
| PDF reading | pypdf | pulls text out of PDF files |
| Embeddings | sentence-transformers | free, runs locally, no API cost |
| Vector storage | ChromaDB | stores + searches embeddings, no server setup needed |
| Answer generation | Claude API | writes the final answer, grounded in retrieved text |
| REST API | FastAPI | exposes this over HTTP, with free auto-generated docs |
| Desktop integration | MCP | lets Claude Desktop call this project directly as a tool |

## Why I'm Building This

<!-- your own words — a sentence or two on why this project, what you wanted to learn -->

## Setup

<!-- filled in once there's actually something to set up -->