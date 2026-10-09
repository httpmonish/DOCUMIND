# DocuMind Failure Modes & Abstention Matrix

Every failure mode and abstention path is strictly tested, deterministic, and mapped to specific domain errors or logged abstention reasons.

| Failure Condition | Outcome | Abstain Reason | LLM Called? | Citations Returned | Proven By Test |
|---|---|---|---|---|---|
| **Empty Vector Index** | `abstained` | `empty_index` | No | None (`()`) | `test_empty_index_returns_before_embedding_or_llm` |
| **Below Relevance Threshold** | `abstained` | `low_score` | No | None (`()`) | `test_low_score_abstains_without_calling_the_llm` |
| **No LLM Configured** (`llm=None`) | `abstained` | `no_llm` | No | Retrieved Chunks | `test_retrieval_only_mode_when_no_llm_is_configured` |
| **LLM Outage / Timeout / 429 / 5xx** | `abstained` | `llm_unavailable` | Attempted | Retrieved Chunks | `test_llm_outage_degrades_to_retrieval_only` |
| **Model Explicit Decline** | `abstained` | `model_declined` | Yes | None (`()`) | `test_model_decline_sentinel_is_an_abstention` |
| **Zero Verified Citations** | `abstained` | `uncited` | Yes | Retrieved Chunks | `test_answer_without_any_valid_citation_is_not_trusted` |
| **Authentication / Credit Exhausted** | `abstained` | `llm_unavailable` | Attempted | Retrieved Chunks | `test_error_mapping_to_domain_errors` |
| **Invalid Input Length / Top-K** | Raises `ValueError` | N/A | No | None | `test_bad_inputs_raise_valueerror` |
