# Examples

Use `H**` prefixes for example directories.

[H00_mini_internet](H00_mini_internet/) provides the shared network and DNS.
Import its unrendered emulator instead of copying the topology:

```python
from examples.H00_mini_internet import build_emulator

emu = build_emulator()
# Add services and DNS records, then render and compile.
```
