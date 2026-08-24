from pathlib import Path
from .pipeline import run

if __name__ == "__main__":
    root=Path(__file__).resolve().parents[2]
    print(run(root))
