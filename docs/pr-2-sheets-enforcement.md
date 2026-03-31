# PR #2: Sheets Abstraction Enforcement

## Overview

This PR enforces consistent Google Sheets access across all tools by eliminating direct `pandas.read_csv()` calls and requiring all sheet reads to go through the `sheets.get_sheet_df()` wrapper.

## Problem

The codebase had mixed patterns for reading Google Sheets data:

**Pattern A (inconsistent)**:
```python
url = build_sheet_url(sheet_url, gid)
df = pd.read_csv(url)
df = df_with_normalized_columns(df)
```

**Pattern B (correct)**:
```python
df = get_sheet_df(url, cache_dir=None)
```

Pattern A:
- Duplicates normalization logic across multiple files
- Misses caching benefits when `cache_dir` is set
- Harder to add retries, timeout handling, or error enrichment later
- No centralized debug logging

## What Changed

### Refactored Files

All tools now use `sheets.get_sheet_df()` exclusively:

1. **`homelab/caddyfile.py`**
   - Replaced manual `pd.read_csv()` + try-except + `df_with_normalized_columns()` with single `get_sheet_df()` call
   - Services sheet and Nodes sheet both use the abstraction

2. **`homelab/deploy.py`**
   - Replaced `pd.read_csv(nodes_url)` with `get_sheet_df(nodes_url, cache_dir=None, debug=False)`

3. **`homelab/dnscontrol.py`**
   - Added `get_sheet_df` to imports
   - Replaced `pd.read_csv()` + `df_with_normalized_columns()` with `get_sheet_df()`
   - Zones sheet and Services sheet both use the abstraction

4. **`homelab/pihole.py`**
   - Added `get_sheet_df` to imports
   - Replaced both `pd.read_csv()` calls (nodes and services) with `get_sheet_df()`

### Code Removed

- ~15 lines of duplicated `pd.read_csv()` + normalization logic
- Custom error handling that was less informative than `get_sheet_df`'s built-in handling

## Benefits

1. **Single Source of Truth**: All sheet reads go through one function
2. **Consistent Caching**: When cache_dir is set, all tools benefit automatically
3. **Better Error Messages**: `get_sheet_df()` provides sheet URL context in errors
4. **Future-Proof**: Adding retries, timeouts, or rate-limiting happens in one place
5. **Debug Logging**: Centralized debug output for sheet fetches

## Testing

- [x] Syntax validation: All modified files compile cleanly
- [ ] Functional: Requires live Google Sheets config (not available in sandbox)

## Future Enhancements

- Consider adding retry logic with exponential backoff to `get_sheet_df()`
- Add request timeout configuration via config file
- Optionally cache sheet metadata (column lists) separately from data
