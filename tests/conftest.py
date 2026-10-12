import os
import sys
from pathlib import Path

# numpy must be imported before dspy: dspy's lazy-import hook breaks numpy's first import, so a
# test module that imports dspy ahead of imagehash (collected earlier) would fail every later one.
import numpy  # noqa: F401

# litellm fetches its price map from GitHub when first imported unless told to use its bundled
# copy; keep the default test run off the network.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
