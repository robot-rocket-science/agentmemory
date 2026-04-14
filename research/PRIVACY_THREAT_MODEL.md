# Privacy Threat Model: MCP-Based Agentic Memory Server

**Date:** 2026-04-09
**Status:** Design document
**Applies to:** agentmemory -- MCP server (JSON-RPC 2.0 via stdin/stdout), SQLite-backed belief/observation/evidence store
**Hard requirements:** REQ-017 (fully local operation), REQ-018 (no telemetry or data collection)

---

## 1. System Overview

The agentic memory system stores observations (immutable conversation turns, file changes, decisions), beliefs (derived claims with confidence and evidence chains), tests (retrieval feedback), and revisions (belief updates with provenance). All data lives in local SQLite with WAL mode.

The MCP server exposes tools (`observe`, `believe`, `search`, `test_result`, `revise`, `checkpoint`, `recover`) over JSON-RPC 2.0 via stdin/stdout to any MCP-compatible client.

Supported clients: Claude Code, ChatGPT (via MCP bridge), Gemini CLI, local models (Ollama, llama.cpp, etc.).

---

## 2. Data Flow Diagram

```
+------------------+     +-------------------+     +------------------+
|                  |     |                   |     |                  |
|  SQLite DB       |---->|  MCP Server       |---->|  LLM Client      |
|  (beliefs,       |     |  (JSON-RPC 2.0    |     |  (Claude Code,   |
|   observations,  |     |   stdin/stdout)   |     |   ChatGPT bridge,|
|   evidence)      |     |                   |     |   Gemini CLI,    |
|                  |<----|                   |<----|   local model)   |
+------------------+     +-------------------+     +------------------+
                                                          |
                                                          | API call
                                                          v
                                                   +------------------+
                                                   |                  |
                                                   |  LLM API         |
                                                   |  Provider        |
                                                   |  (Anthropic,     |
                                                   |   OpenAI,        |
                                                   |   Google)        |
                                                   |                  |
                                                   +------------------+
```

### Data flows:

| # | Flow | Content | Direction | Trust |
|---|------|---------|-----------|-------|
| F1 | SQLite -> MCP Server | Raw beliefs, observations, evidence chains | Read | Trusted (local filesystem) |
| F2 | MCP Server -> LLM Client | Retrieved memory context (JSON-RPC response) | stdin/stdout | Trusted if local process; NOT trusted if over network |
| F3 | LLM Client -> MCP Server | Observe/believe/revise commands with user data | stdin/stdout | Trusted if local process; NOT trusted if over network |
| F4 | LLM Client -> LLM API Provider | Full prompt including injected memory context | HTTPS | **NOT TRUSTED.** The provider sees everything. |
| F5 | MCP Server -> SQLite | New observations, belief updates, checkpoints | Write | Trusted (local filesystem) |
| F6 | LLM API Provider -> LLM Client | Model response | HTTPS | Content trusted for task; provider's handling of our data is not trusted |

**The critical leak is F4.** Every belief, observation, and evidence chain retrieved by the memory system and injected into the prompt is transmitted to the LLM API provider. This is not a bug -- it is how cloud LLMs work. But it means REQ-017 ("no memory data transmitted to external servers") is architecturally violated the moment the LLM client sends the prompt to a cloud API.

---

## 3. Trust Boundaries

### Trusted

| Component | Why |
|-----------|-----|
| Local filesystem | User controls it. SQLite DB, config files, MCP server binary all live here. Standard OS-level access controls apply. |
| MCP transport (stdin/stdout, local) | When MCP client and server are on the same machine communicating via stdio, the pipe is process-local. No network exposure. |
| MCP server process | We control this code. It is auditable. It makes no network calls (REQ-017). |
| SQLite database | Local file. Encrypted at rest if the user enables FileVault/LUKS. No network listener. |

### NOT Trusted

| Component | Why |
|-----------|-----|
| LLM API providers (Anthropic, OpenAI, Google) | They receive the full prompt, including all injected memory content. Their data handling policies are outside our control. They may log prompts, use them for training (unless opted out), or be compelled to disclose them. |
| Python package ecosystem (PyPI) | Supply chain attacks are real and recent. The LiteLLM incident (March 2026) demonstrated that a compromised PyPI package pulled in by MCP servers exfiltrated SSH keys, cloud credentials, and .env files from developer machines. |
| MCP transport over network | If the MCP server is exposed over TCP/HTTP (e.g., remote development, SSH tunnel, Docker), the JSON-RPC traffic contains raw memory content in cleartext unless TLS is added. |
| The LLM itself (as an actor) | The model can be prompt-injected to exfiltrate memory content via tool calls, URLs, or encoded output. The MEXTRA attack (Wang et al., ACL 2025) demonstrated black-box memory extraction from LLM agents. |
| Other MCP servers in the same client | A malicious or compromised MCP server running alongside the memory server could access shared context or exploit confused-deputy patterns. The CoSAI whitepaper (January 2026) documents cross-server trust exploitation as a distinct threat category. |

---

## 4. Threat Catalog

### Threat Classification

Threats are divided into two categories:

**Unmitigable (accept and document):** These are properties of cloud LLMs and the broader software supply chain. No design decision we make eliminates them. The correct response is honest documentation so users understand what they are accepting when they use cloud LLMs.

**Mitigable (design decisions apply):** These are threats where our architectural choices meaningfully reduce the attack surface or impact.

---

### T1: Memory Content Exposure via LLM API

**Classification: UNMITIGABLE -- accept and document**

**Description:** Every belief injected into an LLM prompt is transmitted to the cloud API provider. This is how cloud LLMs work. It is not a bug, an attack surface we can close, or a property of our memory system specifically -- it applies to everything in the prompt.

The provider may log it, use it for training (unless opted out), be compelled to disclose it legally, or expose it in a breach.

**Action:** Document clearly in README and first-run output. Users who require that memory content never leave their machine must use a local LLM backend. We support this (local models are first-class MCP clients). Nothing else to do here.

**Research context:** Zeng et al. (ACL 2024 Findings) demonstrated >0.95 Rouge-L recall on document extraction and ~99% PII extraction accuracy from RAG-injected content. This confirms the exposure is real, not theoretical.

---

### T2: Memory Extraction via Prompt Injection

**Classification: UNMITIGABLE -- accept and document**

**Description:** Prompt injection is a property of LLMs, not of our memory system. If an attacker can inject instructions into the LLM's context (via files, web content, or documents the agent processes), they can instruct the model to output whatever is in context -- memory, system prompt, conversation history. Our memory system does not make this better or worse than any other context source.

The mitigations listed in prior drafts (rate limiting, input validation) do not address this threat. They are appropriate defenses for other things (abuse, malformed inputs) but are security theater against prompt injection specifically.

**Action:** Document that prompt injection is an LLM-level risk that applies to all context sources, not just memory. Users operating in adversarial environments (processing untrusted web content, user-submitted documents, etc.) should use local models. Nothing architecture-specific to do here.

**Research context:** MEXTRA (Wang et al., 2025, arXiv:2502.13172), OWASP LLM Top 10 2025 (#1: prompt injection, >73% of production deployments).

---

### T3: Supply Chain Compromise via Python Dependencies

**Classification: HYGIENE ONLY -- no architectural defense**

**Description:** A dependency (direct or transitive) is compromised to exfiltrate data. Demonstrated in practice: LiteLLM versions 1.82.7-1.82.8 (March 2026, TeamPCP) exfiltrated SSH keys, cloud credentials, .env files, and crypto wallets from developer machines. Ran undetected two weeks.

We cannot prevent a compromised PyPI package. What we can do: minimize the attack surface and detect faster.

**Actions (hygiene only):**
- Minimal dependency tree -- fewer deps = smaller attack surface
- Pin all versions with hashes in uv lockfile
- Audit dependency tree for network code at initialization
- Run with network disabled during CI to verify no dep requires network
- Monitor PyPI advisories

**What this does not do:** Prevent a compromised pinned version. If the package we pin to is compromised before we pin it, hash verification won't help -- we'd pin the compromised hash. Vigilance, not guarantees.

### T4: MCP-over-Network Exposure (Severity: MEDIUM)

**Description:** If a user runs the MCP server over a network transport (TCP, HTTP, WebSocket) instead of stdio -- for remote development, Docker containers, or multi-machine setups -- the JSON-RPC traffic contains raw memory content. Without TLS, this is cleartext on the wire. Even with TLS, the remote endpoint sees everything.

**Likelihood:** Low for default configuration (stdio). Moderate if we ever support network transport or if users improvise one via socat/SSH tunnels.

**Impact:** Full memory content visible to network observers (without TLS) or the remote host (with TLS).

### T5: Data Remnants in Logs, Crash Dumps, and Temp Files (Severity: MEDIUM)

**Description:** Memory content may persist in:
- Python exception tracebacks (which include local variable values)
- OS crash reports (macOS CrashReporter, Linux core dumps)
- Shell history (if MCP commands are logged)
- Editor/IDE logs that capture MCP server output
- `/tmp` files created during processing
- SQLite WAL and journal files (these are features, not bugs, but they are additional copies of data)
- Swap space / hibernation files containing memory-mapped SQLite pages

**Likelihood:** High. Crash dumps and logs are created automatically by the OS.

**Impact:** Memory content recoverable from disk even if the SQLite database is deleted.

### T6: Cross-MCP-Server Trust Exploitation (Severity: MEDIUM)

**Description:** MCP clients (Claude Code, etc.) may connect to multiple MCP servers simultaneously. A malicious server can:
- Read tool descriptions and responses from other servers visible in the shared context
- Inject prompts that cause the LLM to call the memory server's tools and relay results
- Exploit confused-deputy patterns where the LLM acts as a proxy between servers

**Research context:** The CoSAI whitepaper (January 2026) identifies 12 core threat categories and ~40 distinct threats for MCP, including cross-server trust exploitation and confused-deputy vulnerabilities. The first malicious MCP package appeared in September 2025, operating undetected for two weeks while exfiltrating email data.

**Likelihood:** Moderate. Depends on what other MCP servers the user installs.

**Impact:** Memory content accessible to unauthorized MCP servers without the user's knowledge.

### T7: Local Privilege Escalation / Unauthorized Local Access (Severity: LOW-MEDIUM)

**Description:** The SQLite database is a regular file on disk. Any process running as the same user can read it. This includes:
- Other applications
- Browser extensions with filesystem access
- Malware already on the machine

**Likelihood:** Low (requires prior compromise or multi-user systems without proper permissions).

**Impact:** Full memory content readable by any co-located process.

### T8: Differential Privacy Reversal (Severity: CONTEXT-DEPENDENT)

**Description:** If we implement noise injection or differential privacy to obscure sensitive content before sending to cloud LLMs, recent research (early 2026) has shown that LLMs themselves can be used as "oracles" to reverse differential privacy protections and re-identify individuals from supposedly anonymized datasets.

**Likelihood:** High if differential privacy is the chosen mitigation for T1.

**Impact:** Undermines the primary defense, creating a false sense of security.

---

## 5. The Big Question: Cloud LLMs See Your Memory

This is the fundamental tension. REQ-017 says "no memory data transmitted to external servers." But the LLM API provider *is* an external server, and the memory system's entire purpose is to inject relevant context into the LLM prompt.

### What "fully local" actually means

REQ-017 can be satisfied in a strict, narrow sense: the memory system itself (MCP server + SQLite) makes zero network calls. All storage, retrieval, indexing, and lifecycle operations happen locally. The memory server does not phone home, does not transmit data, does not have network code.

But the *consumer* of memory data -- the LLM client -- routinely sends that data to a cloud API. The memory server does not control this. It hands data to the MCP client via stdin/stdout; what the client does with it is outside the server's authority.

This is analogous to an encrypted filesystem: the filesystem keeps data encrypted at rest, but any application that reads the decrypted files can do whatever it wants with the contents.

**We must document this honestly.** Claiming "fully local" without acknowledging this data flow would be dishonest and would violate REQ-015 (no unverified claims) and REQ-016 (documented limitations).

### How other systems handle this

**SuperLocalMemory (V3):** Offers three operating modes that form a privacy-capability gradient:
- Mode A (zero-LLM): Fully local, no API calls. Achieves 74.8% on LoCoMo. All retrieval uses mathematical methods (Fisher-Rao information geometry, sheaf cohomology, Langevin dynamics) instead of LLM calls. Claims EU AI Act compliance "by architectural design" because no data leaves the device.
- Mode B (local LLM via Ollama): Data stays on-device but uses a local model for answer generation.
- Mode C (cloud LLM): Reaches 87.7% on LoCoMo but sends data to the cloud.

The key insight from SLM: **they treat the three modes as a documented spectrum**, not a binary. Mode A is the privacy-safe default. Modes B and C are user-chosen tradeoffs.

Source: [SuperLocalMemory V3 arXiv paper](https://arxiv.org/abs/2603.14588), [SuperLocalMemory website](https://www.superlocalmemory.com/)

**RAG privacy research:** Formal threat models for RAG (Chen et al., arXiv:2509.20324) define four adversary categories based on access level and knowledge. The consistent finding is that any content injected into an LLM prompt is extractable with high accuracy. There is no reliable way to "hide" retrieved content from the model that is processing it.

Source: [RAG Security and Privacy: Formalizing the Threat Model and Attack Surface](https://arxiv.org/pdf/2509.20324)

**Privacy-Aware Decoding (2025):** Research into decoding-time privacy (arXiv:2508.03098) attempts to prevent the LLM from *outputting* private content from retrieved documents, but the provider still *sees* the content in the prompt.

Source: [Privacy-Aware Decoding: Mitigating Privacy Leakage of LLMs in RAG](https://arxiv.org/abs/2508.03098)

### Options and their tradeoffs

| Option | Privacy | Capability | Complexity | Verdict |
|--------|---------|------------|------------|---------|
| **Local models only** | Eliminates T1 entirely | Limited by local hardware. Current best local models (Llama 3.3 70B, Qwen 2.5 72B) are capable but below frontier cloud models. | Low -- just use Ollama/llama.cpp as the MCP client | Viable for many use cases. Should be the recommended privacy-sensitive configuration. |
| **Differential privacy / noise injection** | Theoretically sound, practically broken | Degrades retrieval quality proportionally to noise level | High | **Do not pursue.** LLMs can reverse differential privacy (2026 research). Creates false confidence. |
| **Client-side encryption** | The LLM cannot read encrypted content | Zero. Encrypted beliefs are useless in prompts. | Low | Absurd for this use case. Only relevant for storage-at-rest. |
| **Accept the tradeoff and document it** | Honest about the exposure | Full capability with cloud LLMs | Zero | **Minimum viable approach.** Must be implemented regardless of other options. |
| **Hybrid: sensitivity classification** | Sensitive beliefs local-only, others to cloud | Reduced context for cloud LLMs but most useful context still available | Medium-high. Requires a sensitivity classifier, user-facing controls, per-belief sensitivity tags. | Worth exploring but classification is hard. Misclassification in either direction is bad. |
| **Tiered mode system (SLM approach)** | User chooses their privacy level | Scales with user choice | Medium. Need to support local models as first-class citizens. | **Recommended.** Follows SLM's proven architecture. |

### Recommended approach: Tiered operation with honest documentation

1. **Default mode: local-only retrieval.** The MCP server performs all retrieval, ranking, and context assembly locally using mathematical/statistical methods (no LLM calls for retrieval). This satisfies REQ-017 strictly for the memory system itself.

2. **Document the data flow clearly.** When memory context is injected into a cloud LLM prompt, the user must understand that the API provider sees it. This goes in the README, not buried in a threat model.

3. **Support local models as first-class citizens.** Users who need full privacy can use Ollama, llama.cpp, or any local model backend. The MCP server does not care what the client is -- it serves the same JSON-RPC interface.

4. **Optional sensitivity tagging.** Allow users to tag beliefs as `sensitivity: local_only`. These beliefs are only injected when the MCP client is configured as a local model. This is a user-controlled, opt-in mechanism -- not an automated classifier (automated classifiers would need to be very good to be trustworthy here).

5. **No differential privacy, no encryption-in-transit-to-LLM.** These are security theater for this threat model. Document why.

---

## 6. Mitigations

### T1 and T2: No mitigations -- accept and document

T1 and T2 are properties of cloud LLMs, not of our system. There is nothing to mitigate architecturally. The only action is honest documentation:

- README states clearly that cloud LLM usage means the provider sees all injected memory context
- First-run output reminds the user
- Local model configuration is documented as the privacy-preserving option
- No "fully private" or "fully secure" claims anywhere in documentation

The token budget (REQ-003: 2,000 tokens) incidentally reduces exposure compared to a full context dump, but this is a side effect of good design, not a privacy mitigation.

### T3: Supply Chain -- hygiene actions only

See threat description above. Actions: minimal deps, pinned hashes via uv lockfile, network-disabled CI, PyPI advisory monitoring. No architectural defense available.

### M4: Against T4 (MCP-over-Network)

| Mitigation | Type | Effectiveness |
|------------|------|---------------|
| Minimize dependencies. Hard. | Architectural | Every dependency not present cannot be compromised. The memory server should have the smallest possible dependency tree. |
| Pin all dependency versions with hashes in lock file | Version control | Prevents silent package replacement. Does not protect against compromise of a pinned version. |
| Audit dependency tree for network code | Code review | Identify packages that make outbound connections. Any package in the memory server's tree that phones home is a bug. |
| Run with network disabled during development/testing (offline-first verification per REQ-017) | Testing | Verifies no dependency requires network access. |
| Use `uv` with strict resolution and hash verification | Tooling | uv's lockfile with hashes provides supply chain integrity verification. |
| Consider vendoring critical dependencies | Isolation | Eliminates PyPI as an attack vector for vendored packages, at the cost of update burden. |
| Monitor PyPI advisories for all dependencies | Operations | Early warning, not prevention. |

### M4: Against T4 (MCP-over-Network)

| Mitigation | Type | Effectiveness |
|------------|------|---------------|
| Default to stdio transport only. Do not ship network transport. | Architectural | Eliminates the attack surface entirely in default configuration. |
| If network transport is ever added, require TLS with mutual authentication | Defense in depth | Prevents eavesdropping. Does not protect against compromise of either endpoint. |
| Document that running MCP over network exposes memory content to the network | Documentation | Informed risk acceptance. |

### M5: Against T5 (Data Remnants)

| Mitigation | Type | Effectiveness |
|------------|------|---------------|
| Do not log memory content at INFO level or above. Debug logging of content requires explicit opt-in. | Log hygiene | Prevents casual leakage into log files. |
| Catch exceptions and sanitize tracebacks before they reach log handlers | Defensive coding | Prevents local variables (which may contain memory content) from appearing in crash reports. |
| Document that OS-level encryption (FileVault, LUKS) is recommended for machines storing memory data | User guidance | Protects data at rest including swap, hibernation, and temp files. |
| Set restrictive file permissions on SQLite database (0600) | Access control | Prevents other users on the same system from reading the database. |
| Disable core dumps for the MCP server process (`ulimit -c 0` or `prctl(PR_SET_DUMPABLE, 0)`) | Hardening | Prevents memory dumps from containing belief content. |

### M6: Against T6 (Cross-MCP-Server Trust Exploitation)

| Mitigation | Type | Effectiveness |
|------------|------|---------------|
| Tool descriptions should not leak information about stored content | Information minimization | Prevents other servers from learning about memory content via tool metadata. |
| Memory tools should require explicit user confirmation for bulk operations | Consent | Prevents an LLM (tricked by another server) from silently dumping memory. |
| Document the risk of running untrusted MCP servers alongside the memory server | User guidance | Informed consent. The CoSAI whitepaper recommends this as a baseline. |

### M7: Against T7 (Local Privilege Escalation)

| Mitigation | Type | Effectiveness |
|------------|------|---------------|
| SQLite database file permissions: 0600 (owner read/write only) | Access control | Prevents other users from reading the database. Does not prevent other processes running as the same user. |
| Recommend OS-level disk encryption | User guidance | Protects against offline attacks and device theft. |
| Optional: SQLite encryption extension (SEE, sqlcipher) for at-rest encryption with user-provided key | Defense in depth | Protects database content even if file permissions are bypassed. Adds dependency and complexity. |

---

## 7. Compliance Considerations

### REQ-017 Interpretation

**Strict interpretation (memory system scope):** The MCP server and SQLite database make zero network calls. All memory operations (observe, believe, search, test_result, revise, checkpoint, recover) execute locally. No data is transmitted by the memory system.

**Broad interpretation (end-to-end):** Memory content is transmitted to LLM API providers as part of normal LLM operation. This transmission is performed by the LLM client, not the memory server, but the effect is the same -- memory data reaches external servers.

**Recommendation:** Satisfy the strict interpretation architecturally (verifiable by offline test). Document the broad interpretation honestly. Use language like:

> "The memory system operates fully locally. It makes no network calls and transmits no data. However, when memory context is retrieved and injected into prompts for cloud-based LLMs, the LLM API provider receives that content as part of the prompt. Users who require that memory content never leave their machine should use a local LLM backend."

### GDPR / EU AI Act Relevance

SuperLocalMemory's approach is instructive: their Mode A (zero-LLM) satisfies EU AI Act Regulation 2024/1689 "by architectural design" because no personal data leaves the device during memory operations. Their Mode C (cloud LLM) does not make this claim.

Our system should follow the same pattern:
- With local models: architecturally compliant
- With cloud LLMs: the memory system is compliant; the LLM API usage is governed by the user's agreement with the API provider

Source: [SuperLocalMemory V3 paper](https://arxiv.org/html/2603.14588)

### REQ-018 Interpretation

Zero telemetry means zero telemetry. No usage counters, no error reporting, no analytics, no crash reporting to external services. This is straightforward to implement and verify. The verification method (grep for telemetry/analytics/tracking code) is sound.

---

## 8. Threat Matrix Summary

| ID | Threat | Classification | Primary Action | Residual Risk |
|----|--------|---------------|----------------|---------------|
| T1 | LLM API sees memory content | **UNMITIGABLE** -- accept | Document honestly. Support local models. | Accepted for cloud LLM users. This is the user's tradeoff to make, not ours to solve. |
| T2 | Prompt injection extracts memory | **UNMITIGABLE** -- accept | Document honestly. Recommend local models for adversarial environments. | Accepted. Property of LLMs, not of this system. |
| T3 | Supply chain compromise | **HYGIENE ONLY** | Minimal deps, pinned hashes, network-disabled CI, advisory monitoring | Moderate. No full defense available. |
| T4 | MCP-over-network exposure | Mitigable | stdio-only default, never ship network transport | Low if default maintained |
| T5 | Data remnants in logs/dumps/temp | Mitigable | Log sanitization, debug-only content logging, file permissions | Moderate. OS-level remnants hard to eliminate completely. |
| T6 | Cross-MCP-server exploitation | Mitigable | Information minimization in tool descriptions, confirmation for bulk ops | Moderate. Depends on user's MCP server hygiene. |
| T7 | Local unauthorized access | Mitigable | File permissions (0600), optional DB encryption | Low with basic precautions |
| T8 | Differential privacy reversal | **ELIMINATED** -- do not pursue | Do not implement DP | Zero (by not building it) |

---

## 9. Architectural Decisions Derived from This Threat Model

1. **stdio transport only.** Do not implement network transport for the MCP server. If users need remote access, they can SSH tunnel, but that is their risk to accept.

2. **Minimal dependency tree.** Every dependency is an attack surface. The memory server should depend on Python stdlib + SQLite (stdlib) + a small number of audited packages. Avoid large frameworks.

3. **No telemetry, no analytics, no crash reporting.** Not even opt-in. The code should be auditable for this (REQ-018 verification: grep yields zero hits).

4. **Local model support is a privacy feature, not a nice-to-have.** The MCP interface is model-agnostic by design. Ensure local model clients (Ollama, llama.cpp) are tested and documented as the privacy-recommended configuration.

5. **Token budget (REQ-003) doubles as a privacy feature.** Injecting 2,000 tokens of focused context exposes less data than injecting 54,000 tokens of knowledge dump. This is a concrete privacy benefit of the information-theoretic approach to context selection.

6. **File permissions enforced on database creation.** `os.chmod(db_path, 0o600)` at creation time.

7. **Debug logging of memory content is opt-in, off by default.** Normal operation logs tool call names and timing, never content.

8. **Honest documentation.** The README states clearly that cloud LLM usage means the provider sees memory content. First-run output reminds the user. No "fully private" claims that paper over the cloud LLM data flow.

---

## 10. Open Questions

1. **Sensitivity tagging: is it worth the complexity?** A `local_only` tag on beliefs would let users selectively restrict what reaches cloud LLMs. But this requires the MCP server to know whether the current client is local or cloud -- which it currently does not (and arguably should not, given the principle of transport-agnosticism). This needs design work.

2. **Should the memory server warn when content volume is high?** If a single search returns 2,000 tokens of beliefs about to be injected into a cloud prompt, should the server log a note about data exposure? This is paternalistic but potentially useful for users who forget they are on a cloud backend.

3. **SQLite encryption (sqlcipher) as optional feature?** Adds meaningful at-rest protection but introduces a compiled C dependency, a key management UX problem, and potential performance impact. Worth a separate design discussion.

4. **Observation immutability (REQ-013) has a privacy tension.** If a user wants to delete a specific memory (GDPR Article 17 right to erasure), immutable observations cannot be modified. We may need a "tombstone" mechanism that marks observations as redacted without violating append-only semantics.

---

## Sources

### Research Papers
- [Unveiling Privacy Risks in LLM Agent Memory (MEXTRA)](https://arxiv.org/abs/2502.13172) -- Wang et al., ACL 2025. Memory extraction attacks on LLM agents.
- [RAG Security and Privacy: Formalizing the Threat Model and Attack Surface](https://arxiv.org/pdf/2509.20324) -- Chen et al., 2025. First formal RAG threat model.
- [The Good and The Bad: Exploring Privacy Issues in RAG](https://aclanthology.org/2024.findings-acl.267/) -- Zeng et al., ACL 2024 Findings. Privacy leakage in RAG systems.
- [Privacy-Aware Decoding: Mitigating Privacy Leakage of LLMs in RAG](https://arxiv.org/abs/2508.03098) -- 2025. Decoding-time privacy for RAG.
- [SuperLocalMemory V3: Information-Geometric Foundations for Zero-LLM Enterprise Agent Memory](https://arxiv.org/abs/2603.14588) -- 2026. Three-mode privacy architecture.
- [SuperLocalMemory: Privacy-Preserving Multi-Agent Memory with Bayesian Trust Defense](https://arxiv.org/html/2603.02240) -- 2026. Trust defense against memory poisoning.
- [Mitigating Privacy Risks in RAG via Locally Private Entity Perturbation](https://www.sciencedirect.com/science/article/abs/pii/S0306457325000913) -- 2025. Local differential privacy for RAG.
- [SoK: The Privacy Paradox of Large Language Models](https://arxiv.org/html/2506.12699v1) -- 2025. Comprehensive privacy survey.
- [The Emerged Security and Privacy of LLM Agent: A Survey with Case Studies](https://dl.acm.org/doi/10.1145/3773080) -- ACM Computing Surveys. Broad agent security survey.

### Industry and Standards
- [MCP Security Best Practices (official spec)](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- [CoSAI MCP Security Whitepaper](https://github.com/cosai-oasis/ws4-secure-design-agentic-systems/blob/main/model-context-protocol-security.md) -- Coalition for Secure AI / OASIS Open, January 2026. 12 threat categories, ~40 threats.
- [MAESTRO: Agentic AI Threat Modeling Framework](https://cloudsecurityalliance.org/blog/2025/02/06/agentic-ai-threat-modeling-framework-maestro) -- Cloud Security Alliance, February 2025.
- [OWASP Top 10 for LLM Applications 2025: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [Securing the AI Agent Revolution: Practical Guide to MCP Security](https://www.coalitionforsecureai.org/securing-the-ai-agent-revolution-a-practical-guide-to-mcp-security/) -- CoSAI practical guide.
- [Enterprise-Grade Security for MCP](https://arxiv.org/pdf/2504.08623) -- 2025.

### Incidents
- [LiteLLM PyPI Supply Chain Attack (March 2026)](https://www.infoq.com/news/2026/03/litellm-supply-chain-attack/) -- Compromised package exfiltrated credentials from MCP server users.
- [LiteLLM Security Update](https://docs.litellm.ai/blog/security-update-march-2026) -- Official incident report.
- [Wiz analysis of TeamPCP / LiteLLM attack](https://www.wiz.io/blog/threes-a-crowd-teampcp-trojanizes-litellm-in-continuation-of-campaign)
- [Snyk analysis of poisoned security scanner in LiteLLM chain](https://snyk.io/blog/poisoned-security-scanner-backdooring-litellm/)
- [Differential Privacy Reversal via LLM Feedback (2026)](https://medium.com/@instatunnel/it-162aee1dbfe5) -- LLMs used to reverse differential privacy protections.

### MCP Security Analysis
- [Red Hat: MCP Security Risks and Controls](https://www.redhat.com/en/blog/model-context-protocol-mcp-understanding-security-risks-and-controls)
- [SentinelOne: MCP Security Complete Guide](https://www.sentinelone.com/cybersecurity-101/cybersecurity/mcp-security/)
- [Practical DevSecOps: MCP Security Vulnerabilities](https://www.practical-devsecops.com/mcp-security-vulnerabilities/)
- [SOC Prime: MCP Security Risks and Mitigations](https://socprime.com/blog/mcp-security-risks-and-mitigations/)
