"""Put the repo root on `sys.path` so the tests can `import labscripts`.

A host script run as `./gen_clab_topology` gets its own directory on
`sys.path[0]` for free; a test module collected out of `tests/` does not.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
