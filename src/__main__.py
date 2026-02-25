"""
Called by ``python -m src``.
Delegates to src.__init__.main() which dispatches CLI or HTTP.
"""

from src import main

main()
