<!-- CODEGRAPH_START -->
## CodeGraph

This project has a CodeGraph MCP server (`codegraph_*` tools) configured. CodeGraph is a tree-sitter-parsed knowledge graph of every symbol, edge, and file. Reads are sub-millisecond and return structural information grep cannot.

### When to prefer codegraph over native search

Use codegraph for structural questions: what calls what, what would break, where a symbol is defined, or what a signature/source looks like. Use native grep/read only for literal text queries or after a specific file is already known.

| Question | Tool |
|---|---|
| Where is X defined? / Find symbol X | `codegraph_search` |
| What calls Y? | `codegraph_callers` |
| What does Y call? | `codegraph_callees` |
| What would break if Z changes? | `codegraph_impact` |
| Show Y source/signature | `codegraph_node` |
| Get focused task context | `codegraph_context` |
| Inspect several related symbols/files | `codegraph_explore` |
| List files under a path | `codegraph_files` |
| Check index health | `codegraph_status` |

If `.codegraph/` is missing or the server says the project is not initialized, ask before running `codegraph init -i`.
<!-- CODEGRAPH_END -->

## Architecture Documents

Keep architecture content in one source file.

### Source of truth

- `docs/system-architecture.html` is the only interactive architecture document. It contains architecture views, nodes, links, labels, summaries, details, and the right-side database schema panel.
- Do not add generated architecture duplicates for the same content. Update `docs/system-architecture.html` directly.

### Required workflow after architecture changes

After changing `docs/system-architecture.html` in any way that affects views, processes, node labels, links, database schema, or details:

```bash
node docs/scripts/validate-x6-architecture-runtime.mjs
node docs/scripts/validate-business-flow-x6-labels.mjs
```

### Database model rules

- Data model table nodes must show a Chinese short name plus the English table name, for example `决策记录\nDECISION_RECORD`.
- The right-side `databaseSchema` section in `docs/system-architecture.html` must remain the detailed database design reference.
- If a table is added, renamed, or removed, update `dataModel.nodes`, `databaseSchema`, and validation assertions together.

## 开发规则
- 开发的应用,后台,服务,要可支持 k8s 无状态 部署
- 需要持续存储的内容,遵循 k8s 设计规范
