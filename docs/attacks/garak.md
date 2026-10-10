# Garak (Vulnerability Scanning)

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Run a broad library of built-in probes against the target and collect the results  
**Query Budget**: Depends on the probes selected (100+ built-in probes)  
**Key Feature**: Comprehensive coverage; runs [Garak](https://github.com/NVIDIA/garak) as a subprocess against an OpenAI-compatible HTTP endpoint

```python
from interplay.red_teaming import run_garak

result = run_garak(
    target_url="https://your-target/v1",
    probe_file="probes.jsonl",
    output_dir="output/garak",
)
print(result["success"], result["returncode"])
```

`run_garak` returns a dict with `success`, `stdout`, `stderr` and `returncode`. `create_custom_config`
builds a Garak config for your endpoint and `parse_garak_results` summarizes a finished run.

## Notes

- Requires the `garak` extra (`pip install 'interplay-adversarial[garak]'`, or `uv sync --extra garak` in a clone), which installs Garak. Without it, `run_garak` raises a clear error.
- Garak runs as an external process, so its own configuration and output format apply.
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Garak: https://github.com/NVIDIA/garak
