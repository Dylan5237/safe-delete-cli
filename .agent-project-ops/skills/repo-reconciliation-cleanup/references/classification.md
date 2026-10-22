# Classification

Deterministic KIND via:

```bash
python scripts/classify_ref.py --cwd <repo> --tip origin/main --ref BRANCH
# → KIND=... ahead=N behind=N tip=... ref=...
```

Semantics of `git rev-list --left-right --count TIP...REF`:

- `behind` (left) = commits only on tip
- `ahead` (right) = commits only on ref

| KIND | ahead | behind | Default disposition |
| --- | ---: | ---: | --- |
| SAME | 0 | 0 | keep if default; else delete alias |
| ANCESTOR | 0 | >0 | low-risk delete after disposer auth |
| AHEAD | >0 | 0 | keep / merge path |
| DIVERGED | >0 | >0 | reclaim or written abandon — **no auto-delete** |

Also classify **local default vs `origin/<default>`** with the same matrix (see edge case E-DIVERGE).

Re-run classify immediately before each delete; if KIND≠ANCESTOR, skip.
