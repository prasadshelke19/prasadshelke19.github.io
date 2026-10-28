"""Package the explorer into one HTML file that opens privately/offline."""
import argparse
from pathlib import Path
import re


def make_preview(output):
    root = Path(__file__).parents[1]
    html = (root / "index.html").read_text()
    html = html.replace('<link rel="stylesheet" href="styles.css">', '<style>' + (root / "styles.css").read_text() + '</style>')
    html = re.sub(r'\s*<link rel="icon"[^>]+>', '', html)
    def inline(match):
        source = (root / match.group(1)).read_text()
        return '<script>\n' + source.replace('</script', '<\\/script') + '\n</script>'
    html = re.sub(r'<script src="([^"]+)"[^>]*></script>', inline, html)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(f"Offline preview: {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    make_preview(parser.parse_args().output)
