import os
import sys

# the lambda has src/ as its package root, so imports there are flat
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
