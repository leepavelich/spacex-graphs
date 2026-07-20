"""Entry point kept for CI and Docker: `python3 graphs.py [--output]`.

The implementation lives in the spacex_graphs package.
"""

from spacex_graphs.cli import main

if __name__ == "__main__":
    main()
