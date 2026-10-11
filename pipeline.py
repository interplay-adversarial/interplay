"""Entry point for `data-designer ... pipeline.py` from a clone of the repository.

The pipeline itself lives in the installed package (interplay/pipeline.py) so that
`pip install interplay-adversarial` users get it too; see the `interplay probes` command.
"""

from interplay.pipeline import load_config_builder  # noqa: F401
