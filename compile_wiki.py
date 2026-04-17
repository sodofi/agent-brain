"""
One-time script to compile wiki/ from all existing raw/ content.
Run this once to bootstrap the wiki, then the bot handles incremental updates.
"""

import asyncio
import logging
from pathlib import Path

import httpx

from config import OBSIDIAN_VAULT_PATH, OPENROUTER_API_KEY

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

VAULT = Path(OBSIDIAN_VAULT_PATH)
RAW_DIR = VAULT / "raw"
WIKI_DIR = VAULT / "wiki"


async def compile_wiki_for_file(raw_path: Path):
    """Read a raw file and generate an organized wiki version."""
    content = raw_path.read_text().strip()

    # Skip empty/stub files
    if len(content) < 100:
        log.info(f"Skipping {raw_path.name} (too short)")
        return

    wiki_path = WIKI_DIR / raw_path.name
    topic_name = raw_path.stem.replace("-", " ").title()

    log.info(f"Compiling wiki for {raw_path.name} ({len(content)} chars)...")

    # For large files, send the most recent entries (top of file) + a sample from older entries
    if len(content) > 12000:
        # Take first 8000 chars (recent) and last 4000 chars (older context)
        truncated = content[:8000] + "\n\n[...middle entries omitted...]\n\n" + content[-4000:]
    else:
        truncated = content

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "content-type": "application/json",
                },
                json={
                    "model": "anthropic/claude-3.5-haiku",
                    "max_tokens": 4000,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"You are compiling an organized wiki page from raw notes for a personal knowledge base.\n\n"
                                f"Topic: {topic_name}\n"
                                f"Source file: raw/{raw_path.name}\n\n"
                                f"RAW CONTENT:\n```\n{truncated}\n```\n\n"
                                f"Create an organized wiki page following these rules:\n"
                                f"- Start with: # {topic_name}\n"
                                f"- First paragraph: one-paragraph summary of this topic area\n"
                                f"- Organize by theme/concept using ## subheadings — NOT by date\n"
                                f"- Group related ideas together\n"
                                f"- Summarize and synthesize — don't copy raw entries verbatim\n"
                                f"- Use [[wiki/filename]] links to reference related topics when relevant\n"
                                f"  (related wiki pages: research-trends, content-ideas, content-tips, ethereum-news, "
                                f"future-goals, curiosity-map, todos, build-ideas, inbox)\n"
                                f"- Keep it concise and scannable — this is a reference wiki\n"
                                f"- Note the source: 'Compiled from [[raw/{raw_path.name}]]' at the bottom\n"
                                f"- Return raw markdown only, no code blocks"
                            ),
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            wiki_content = data["choices"][0]["message"]["content"].strip()

            if len(wiki_content) > 100:
                wiki_path.write_text(wiki_content + "\n")
                log.info(f"Wrote {wiki_path.name} ({len(wiki_content)} chars)")
            else:
                log.warning(f"Response too short for {raw_path.name}, skipping")

    except Exception as e:
        log.error(f"Failed to compile {raw_path.name}: {e}")


async def build_index():
    """Build the wiki INDEX.md."""
    index_path = WIKI_DIR / "INDEX.md"
    lines = ["# Wiki Index\n", "All organized topics in this knowledge base.\n", "---\n"]

    for f in sorted(WIKI_DIR.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        name = f.stem.replace("-", " ").title()
        # Read first non-heading line as description
        content = f.read_text()
        desc = ""
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                desc = line[:120]
                break
        lines.append(f"- [[wiki/{f.name}|{name}]] — {desc}")

    lines.append("")
    index_path.write_text("\n".join(lines))
    log.info("Index built.")


async def main():
    if not OPENROUTER_API_KEY:
        log.error("OPENROUTER_API_KEY not set")
        return

    WIKI_DIR.mkdir(exist_ok=True)

    raw_files = sorted(RAW_DIR.glob("*.md"))
    log.info(f"Found {len(raw_files)} raw files to process")

    # Process sequentially to avoid rate limits
    for raw_path in raw_files:
        await compile_wiki_for_file(raw_path)

    await build_index()
    log.info("Wiki compilation complete.")


if __name__ == "__main__":
    asyncio.run(main())
